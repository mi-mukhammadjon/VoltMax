from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from django.shortcuts import get_object_or_404

from .models import OTPCode, RfidCard, Vehicle
from .serializers import (
    RfidCardSerializer, SendOTPSerializer, VehicleSerializer, VerifyOTPSerializer,
)
from .telegram_gateway import send_verification_code, TelegramGatewayError


class OTPThrottle(AnonRateThrottle):
    scope = 'otp'


class SendOTPView(APIView):
    """POST /api/auth/send-otp/ {phone} — OTP kod generatsiya qilib, Telegram Gateway
    (https://gateway.telegram.org) orqali yuboradi. DEBUG rejimida, agar token
    sozlanmagan yoki yuborish muvaffaqiyatsiz bo'lsa, kod javobda ham qaytariladi
    (faqat sinov uchun — productionda TELEGRAM_GATEWAY_TOKEN albatta kerak).

    Ochiq bo'lishi shart: foydalanuvchi hali tizimga kirmagan."""
    permission_classes = [permissions.AllowAny]
    throttle_classes = [OTPThrottle]

    def post(self, request):
        serializer = SendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data['phone']

        otp = OTPCode.generate(phone)

        # Ikki kanal: avval Telegram (arzon), ishlamasa SMS. Bitta kanal
        # bitta nuqta edi — hisobda mablag' tugasa hech kim kira olmasdi.
        from .otp_delivery import DeliveryError, deliver

        problem = None
        try:
            channel, _skipped = deliver(phone, otp.code)
            otp.sent_via = channel
            otp.save(update_fields=['sent_via'])
        except DeliveryError as exc:
            problem = str(exc)

        data = {'success': problem is None}
        if settings.DEBUG:
            # Ishlab chiqishda kod javobda ham qaytariladi: shlyuz
            # sozlanmagan mashinada ham ilovani sinab ko'rish kerak
            data['devCode'] = otp.code
            if problem:
                data['deliveryError'] = problem
        elif problem:
            return Response(
                {'detail': "Kodni yuborib bo'lmadi, birozdan so'ng qayta urinib ko'ring"},
                status=502)
        return Response(data)


class VerifyOTPView(APIView):
    """POST /api/auth/verify-otp/ {phone, code} — kodni tekshiradi, foydalanuvchini
    topadi/yaratadi (username=telefon) va JWT access/refresh token qaytaradi.

    Ochiq bo'lishi shart: token aynan shu yerda beriladi."""
    permission_classes = [permissions.AllowAny]
    throttle_classes = [OTPThrottle]

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data['phone']
        code = serializer.validated_data['code']

        # Oxirgi YUBORILGAN kod qidiriladi, kod bo'yicha emas: aks holda
        # noto'g'ri terilgan kod hech qaysi yozuvga tushmasdi va urinishlar
        # sanalmasdi — chegaraning ma'nosi qolmasdi.
        otp = (OTPCode.objects
               .filter(phone=phone, is_used=False)
               .order_by('-created_at').first())

        if otp is None or otp.is_expired:
            return Response({'detail': "Kod noto'g'ri yoki muddati o'tgan"}, status=400)

        if otp.is_locked:
            return Response(
                {'detail': "Urinishlar soni tugadi. Yangi kod so'rang"}, status=429)

        if otp.code != code:
            locked = otp.wrong_attempt()
            return Response(
                {'detail': "Urinishlar soni tugadi. Yangi kod so'rang" if locked
                           else "Kod noto'g'ri"},
                status=429 if locked else 400)

        otp.is_used = True
        otp.save(update_fields=['is_used'])

        user, _ = User.objects.get_or_create(username=phone)
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])

        refresh = RefreshToken.for_user(user)
        # `name` ham qaytariladi — qayta kirgan foydalanuvchi bosh ekranda darhol
        # ismi bilan kutib olinadi (profil so'rovi kelishini kutmasdan).
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'phone': phone,
            'name': user.first_name,
        })


class ProfileView(APIView):
    """GET/PATCH/DELETE /api/auth/profile/ — ProfileScreen'dagi "Profilni tahrirlash"
    va "Profilni o'chirish" uchun. Telefon (username) o'zgartirilmaydi — u login
    identifikatori, faqat ism tahrirlanadi."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({'phone': request.user.username, 'name': request.user.first_name})

    def patch(self, request):
        name = (request.data.get('name') or '').strip()[:150]
        request.user.first_name = name
        request.user.save(update_fields=['first_name'])
        return Response({'phone': request.user.username, 'name': request.user.first_name})

    def delete(self, request):
        # ChargingSession/WalletBalance/Transaction'dagi FK'lar CASCADE bo'lgani
        # uchun bog'liq barcha ma'lumotlar ham avtomatik o'chadi.
        request.user.delete()
        return Response(status=204)


class VehicleListView(generics.ListCreateAPIView):
    """GET/POST /api/auth/vehicles/ — "Mening transport vositalarim"."""
    serializer_class = VehicleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Vehicle.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class VehicleDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/auth/vehicles/<id>/"""
    serializer_class = VehicleSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Vehicle.objects.filter(user=self.request.user)


class MyRfidCardsView(generics.ListAPIView):
    """GET /api/auth/rfid-cards/ — foydalanuvchining o'z kartalari."""

    serializer_class = RfidCardSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return RfidCard.objects.filter(user=self.request.user).select_related('company')


class MyRfidCardBlockView(APIView):
    """POST /api/auth/rfid-cards/<id>/block/ — kartani bloklash/ochish.

    Karta yo'qolganda foydalanuvchi uni O'ZI darhol bloklashi kerak —
    operatorga qo'ng'iroq qilib kutish xavfli. Ochish esa faqat o'zi
    bloklagan kartada mumkin: operator bloklagan bo'lsa (firibgarlik,
    qarz) foydalanuvchi uni qayta yoqa olmaydi.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        card = get_object_or_404(RfidCard, pk=pk, user=request.user)
        block = request.data.get('block', True)

        if block:
            card.status = RfidCard.Status.BLOCKED
            card.blocked_by_owner = True
        else:
            if not card.blocked_by_owner:
                return Response(
                    {'detail': "Bu kartani operator bloklagan — o'zingiz ocha olmaysiz. "
                               "Qo'llab-quvvatlash xizmatiga murojaat qiling."},
                    status=403,
                )
            card.status = RfidCard.Status.ACTIVE
            card.blocked_by_owner = False

        card.save(update_fields=['status', 'blocked_by_owner'])
        return Response(RfidCardSerializer(card).data)


class LogoutView(APIView):
    """POST /api/auth/logout/ {refresh} — tokenni HAQIQATAN bekor qiladi.

    Ilgari "chiqish" faqat telefondagi nusxani o'chirardi: server tomonda
    `refresh` tokeni yana bir oy amal qilaverardi. Telefon boshqa odamga
    o'tsa yoki token oshkor bo'lsa, uni to'xtatishning yo'li yo'q edi.

    Token yaroqsiz bo'lsa ham 205 qaytariladi: foydalanuvchi baribir
    chiqmoqchi va "chiqib bo'lmadi" degan xabar unga hech narsa bermaydi.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from rest_framework_simplejwt.exceptions import TokenError
        from rest_framework_simplejwt.tokens import RefreshToken

        raw = request.data.get('refresh')
        if raw:
            try:
                RefreshToken(raw).blacklist()
            except TokenError:
                pass

        return Response(status=205)
