from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import Station, Review
from .serializers import StationSerializer, ReviewSerializer


class StationListView(generics.ListAPIView):
    """GET /api/stations/ — mobil ilovadagi StationsAPI.list() uchun.

    ATAYLAB ochiq: xaritani ko'rish uchun ro'yxatdan o'tish shart emas —
    odam avval stansiyalarni ko'radi, keyin qaror qiladi.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = StationSerializer
    queryset = Station.objects.prefetch_related('connectors', 'amenities', 'reviews').all()


class StationDetailView(generics.RetrieveAPIView):
    """GET /api/stations/<id>/ — mobil ilovadagi StationsAPI.getById() uchun.

    Ro'yxat kabi ochiq: kirmagan odam ham stansiya haqida o'qiy oladi.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = StationSerializer
    queryset = Station.objects.prefetch_related('connectors', 'amenities', 'reviews').all()


class ReviewListView(generics.ListCreateAPIView):
    """GET/POST /api/stations/<station_id>/reviews/ — stansiya sharhlari.
    Bitta foydalanuvchi bitta stansiyaga faqat bitta sharh qoldira oladi;
    qayta yuborilsa mavjud sharh yangilanadi."""
    serializer_class = ReviewSerializer
    # Sharh yozish tez-tez takrorlanadigan amal emas — spamni to'samiz
    throttle_scope = 'review'
    throttle_classes = [ScopedRateThrottle]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [permissions.IsAuthenticated()]
        return [permissions.AllowAny()]

    def get_queryset(self):
        return Review.objects.filter(station_id=self.kwargs['station_id']).select_related('user')

    def perform_create(self, serializer):
        station_id = self.kwargs['station_id']
        existing = Review.objects.filter(station_id=station_id, user=self.request.user).first()
        if existing:
            existing.rating = serializer.validated_data['rating']
            existing.comment = serializer.validated_data.get('comment', '')
            existing.save(update_fields=['rating', 'comment'])
            serializer.instance = existing
            return
        try:
            serializer.save(user=self.request.user, station_id=station_id)
        except Exception as exc:
            raise ValidationError(str(exc))


class PromoCheckView(APIView):
    """POST /api/stations/promo/check/ {stationId, code} — promo-kodni tekshiradi.

    Ilova kodni sessiya boshlashdan OLDIN tekshiradi va foydalanuvchiga
    yangi narxni ko'rsatadi. Aks holda kod noto'g'ri ekani faqat
    zaryadlash tugagach ma'lum bo'lardi — eng noqulay payt.
    """
    permission_classes = [permissions.IsAuthenticated]
    # Promo-kodni TANLASH mumkin edi: kod qisqa, urinishlar esa
    # cheklanmagan bo'lsa uni topib olish shunchaki vaqt masalasi
    throttle_scope = 'promo'
    throttle_classes = [ScopedRateThrottle]

    def post(self, request):
        from stations import pricing

        station = get_object_or_404(Station, pk=request.data.get('stationId'))
        code = (request.data.get('code') or '').strip()

        offer, error = pricing.check_promo(station, code)
        if error:
            return Response({'valid': False, 'detail': error}, status=400)

        without = pricing.resolve(station)
        with_code = pricing.resolve(station, promo_code=code)
        return Response({
            'valid': True,
            'title': offer.title,
            'description': offer.description,
            'pricePerKwh': with_code.price,
            'originalPricePerKwh': without.price,
            'savedPerKwh': max(0, without.price - with_code.price),
        })


class StationReportView(APIView):
    """POST /api/stations/<id>/report/ — foydalanuvchi nosozlik haqida xabar beradi.

    Ilova ilgari bu tugmani bosganda «xabaringiz qabul qilindi» deb
    yozardi va hech qayerga hech narsa yubormasdi. Buzuq charger
    oldida turgan odam operator endi biladi deb o'ylab ketardi.

    Xabar stansiya holatini O'ZGARTIRMAYDI: u tekshirilmagan signal
    va operator ro'yxatida shunday belgilanadi.
    """
    permission_classes = [permissions.IsAuthenticated]
    # Cheklovsiz bo'lsa ro'yxatni to'ldirib, haqiqiy nosozliklarni
    # ko'rinmas qilib qo'yish mumkin edi
    throttle_scope = 'report'
    throttle_classes = [ScopedRateThrottle]

    def post(self, request, pk):
        from stations import reports

        station = get_object_or_404(Station, pk=pk)
        try:
            report, issue, created = reports.submit(
                request.user, station, request.data.get('note') or '')
        except reports.ReportError as error:
            return Response({'detail': str(error)}, status=429)

        return Response({
            'accepted': True,
            # Ilova javobni shu asosda yozadi: allaqachon ma'lum bo'lgan
            # muammo uchun «xabar qildik» deyish noto'g'ri bo'lardi
            'alreadyKnown': not created,
            'issueId': issue.pk if issue else None,
        }, status=201)
