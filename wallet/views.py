from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import WalletBalance, Transaction
from .serializers import WalletBalanceSerializer, TransactionSerializer, TopUpSerializer


class BalanceView(APIView):
    """GET /api/wallet/balance/ — mobil ilovadagi WalletAPI.getBalance()."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        wallet, _ = WalletBalance.objects.get_or_create(user=request.user)
        return Response(WalletBalanceSerializer(wallet).data)


class TransactionListView(generics.ListAPIView):
    """GET /api/wallet/transactions/ — mobil ilovadagi WalletAPI.getTransactions()."""
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Transaction.objects.filter(user=self.request.user)


class ProviderListView(APIView):
    """GET /api/wallet/providers/ — ilovadagi to'ldirish usullari ro'yxati.

    Faqat yoqilgan VA sozlangan tizimlar chiqadi: identifikatorlari
    to'ldirilmagan tizimni ko'rsatish — foydalanuvchini ishlamaydigan
    to'lovga yuborish demakdir.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from management.models import PaymentProvider, SiteSettings

        settings_obj = SiteSettings.load()
        rows = [
            {'code': p.code, 'name': p.name}
            for p in PaymentProvider.objects.filter(is_active=True)
            if p.is_configured
        ]
        return Response({
            'results': rows,
            'minAmount': settings_obj.min_topup,
            'maxAmount': settings_obj.max_topup,
        })


class TopUpView(APIView):
    """POST /api/wallet/topup/ {amount, provider} — to'lov havolasini qaytaradi.

    Balans BU YERDA oshmaydi: pul haqiqatan kelganini faqat to'lov tizimi
    tasdiqlaydi (`/api/payments/...` endpoint'lari). Ilgari bu yerda balans
    to'g'ridan-to'g'ri oshirilardi — ya'ni pulsiz to'ldirish mumkin edi.

    To'lov tizimi ko'rsatilmasa yoki sozlanmagan bo'lsa xato qaytadi:
    "to'ldirdim, lekin pul yo'q" holatidan ko'ra ochiq xato yaxshiroq.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from management.models import PaymentProvider, SiteSettings

        from . import click, payme
        from .models import PaymentOrder

        serializer = TopUpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        amount = serializer.validated_data['amount']

        settings_obj = SiteSettings.load()
        if amount < settings_obj.min_topup:
            return Response(
                {'detail': f"Eng kam summa — {settings_obj.min_topup} so'm"}, status=400)
        if settings_obj.max_topup and amount > settings_obj.max_topup:
            return Response(
                {'detail': f"Eng ko'p summa — {settings_obj.max_topup} so'm"}, status=400)

        code = (request.data.get('provider') or '').strip().lower()
        query = PaymentProvider.objects.filter(is_active=True)
        provider = query.filter(code=code).first() if code else query.first()

        if provider is None:
            return Response({'detail': "To'lov tizimi topilmadi"}, status=400)
        if not provider.is_configured:
            return Response(
                {'detail': f'{provider.name} hali sozlanmagan'}, status=503)

        order = PaymentOrder.objects.create(
            user=request.user, provider=provider, amount=amount)

        builder = {'payme': payme.checkout_url, 'click': click.checkout_url}.get(
            provider.code)
        if builder is None:
            # Noma'lum tizim: buyurtma yozildi, lekin havola yasab bo'lmaydi
            return Response({'detail': f"{provider.name} uchun havola sozlanmagan"},
                            status=503)

        return Response({
            'orderId': order.pk,
            'provider': provider.code,
            'amount': amount,
            'checkoutUrl': builder(order),
        }, status=201)


class PaymentStatusView(APIView):
    """GET /api/wallet/payments/<id>/ — to'lov holati.

    Ilova to'lovdan qaytgach shu manzilni so'rab turadi: pul kelgani haqida
    xabarni to'lov tizimi BIZGA yuboradi, ilovaga emas.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        from .models import PaymentOrder

        order = get_object_or_404(PaymentOrder, pk=pk, user=request.user)
        return Response({
            'orderId': order.pk,
            'state': order.state,
            'stateLabel': order.get_state_display(),
            'paid': order.state == PaymentOrder.State.PAID,
            'amount': order.amount,
        })


class CardListView(APIView):
    """GET/POST /api/wallet/cards/ — biriktirilgan kartalar.

    POST karta raqamini qabul qiladi va uni provayderga uzatadi. Raqam
    BAZAGA YOZILMAYDI: `wallet/cards.py` dan naryoga o'tmaydi.

    `sensitive_post_parameters` — Django xato sahifasida va Sentry
    hisobotida bu maydonlar `***` bilan almashtiriladi. Usiz bitta
    kutilmagan istisno butun karta raqamini logga chiqarardi.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .serializers import SavedCardSerializer

        cards = request.user.cards.select_related('provider').all()
        return Response({'results': SavedCardSerializer(cards, many=True).data})

    # `dispatch` da: DRF ning `Request` obyekti Django `HttpRequest` emas
    # va dekorator uni tanimaydi. Bu yerda esa hali asl so'rov turadi.
    @method_decorator(sensitive_post_parameters('pan', 'card_number', 'expiry'))
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request):
        from management.models import PaymentProvider

        from . import cards as card_flow
        from .serializers import SavedCardSerializer

        code = (request.data.get('provider') or '').strip().lower()
        query = PaymentProvider.objects.filter(is_active=True)
        provider = query.filter(code=code).first() if code else query.first()
        if provider is None:
            return Response({'detail': "To'lov tizimi topilmadi"}, status=400)

        try:
            card = card_flow.register(
                request.user, provider,
                request.data.get('pan') or request.data.get('card_number') or '',
                request.data.get('expiry') or '',
            )
            card_flow.send_code(card)
        except card_flow.CardError as error:
            return Response({'detail': str(error)}, status=400)

        return Response(SavedCardSerializer(card).data, status=201)


class CardVerifyView(APIView):
    """POST /api/wallet/cards/<id>/verify/ — SMS kodni tasdiqlash."""
    permission_classes = [permissions.IsAuthenticated]

    @method_decorator(sensitive_post_parameters('code'))
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request, pk):
        from . import cards as card_flow
        from .models import SavedCard
        from .serializers import SavedCardSerializer

        card = get_object_or_404(SavedCard, pk=pk, user=request.user)
        try:
            card_flow.verify(card, request.data.get('code') or '')
        except card_flow.CardError as error:
            return Response({'detail': str(error)}, status=400)

        return Response(SavedCardSerializer(card).data)


class CardDetailView(APIView):
    """DELETE /api/wallet/cards/<id>/ — kartani o'chirish."""
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk):
        from . import cards as card_flow
        from .models import SavedCard

        card = get_object_or_404(SavedCard, pk=pk, user=request.user)
        card_flow.remove(card)
        return Response(status=204)

    def post(self, request, pk):
        """Asosiy karta qilib belgilash."""
        from .models import SavedCard
        from .serializers import SavedCardSerializer

        card = get_object_or_404(SavedCard, pk=pk, user=request.user)
        card.make_default()
        return Response(SavedCardSerializer(card).data)


class CardChargeView(APIView):
    """POST /api/wallet/cards/<id>/charge/ — saqlangan karta bilan to'ldirish.

    Brauzerga o'tish yo'q: bir bosishda hamyon to'ladi.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        from management.models import SiteSettings

        from . import cards as card_flow
        from .models import SavedCard

        card = get_object_or_404(SavedCard, pk=pk, user=request.user)

        serializer = TopUpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        amount = serializer.validated_data['amount']

        settings_obj = SiteSettings.load()
        if amount < settings_obj.min_topup:
            return Response(
                {'detail': f"Eng kam summa — {settings_obj.min_topup} so'm"}, status=400)
        if settings_obj.max_topup and amount > settings_obj.max_topup:
            return Response(
                {'detail': f"Eng ko'p summa — {settings_obj.max_topup} so'm"}, status=400)

        try:
            order = card_flow.charge(card, amount)
        except card_flow.CardError as error:
            return Response({'detail': str(error)}, status=400)

        from .models import WalletBalance

        balance = WalletBalance.objects.filter(user=request.user).first()
        return Response({
            'orderId': order.pk,
            'paid': True,
            'amount': order.amount,
            'balance': balance.amount if balance else 0,
        }, status=201)


class AutoTopUpView(APIView):
    """GET/PUT/DELETE /api/wallet/auto-topup/ — avtomatik to'ldirish.

    Zaryadlash paytida pul tugasa sessiya to'xtaydi va odam yarim
    zaryadlangan mashina bilan qoladi — ko'pincha yerto'la parkovkada.
    Bu sozlama shu holatning oldini oladi.

    Chegaralar SERVER tomonda: ilova ularni yubormaydi va o'zgartira
    olmaydi. Avtomatik pul yechish ishonchni eng tez yo'qotadigan
    narsa, shuning uchun chegara foydalanuvchining qo'lida bo'lmaydi.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .models import AutoTopUp
        from .serializers import AutoTopUpSerializer

        row = AutoTopUp.objects.filter(user=request.user).first()
        if row is None:
            return Response({'enabled': False})
        return Response({'enabled': True, **AutoTopUpSerializer(row).data})

    def put(self, request):
        from management.models import SiteSettings

        from .models import AutoTopUp, SavedCard
        from .serializers import AutoTopUpSerializer

        card = get_object_or_404(
            SavedCard, pk=request.data.get('cardId'), user=request.user)
        if not card.is_usable:
            return Response({'detail': 'Karta tasdiqlanmagan'}, status=400)

        settings_obj = SiteSettings.load()
        amount = int(request.data.get('amount') or 50000)
        threshold = int(request.data.get('threshold') or 20000)

        if amount < settings_obj.min_topup:
            return Response(
                {'detail': f"Eng kam summa — {settings_obj.min_topup} so'm"}, status=400)
        # Chegara summadan katta bo'lsa to'ldirish darhol yana ishga
        # tushadi va halqa hosil bo'ladi
        if threshold >= amount:
            return Response(
                {'detail': "Chegara to'ldirish summasidan kichik bo'lishi kerak"},
                status=400)

        row, _ = AutoTopUp.objects.get_or_create(user=request.user, defaults={'card': card})
        row.card = card
        row.amount = amount
        row.threshold = threshold
        row.is_active = bool(request.data.get('isActive', True))
        # Yangi sozlashda xatolar hisobi tozalanadi
        row.fail_streak = 0
        row.last_error = ''
        row.save()

        return Response({'enabled': True, **AutoTopUpSerializer(row).data})

    def delete(self, request):
        from .models import AutoTopUp

        AutoTopUp.objects.filter(user=request.user).delete()
        return Response({'enabled': False}, status=200)
