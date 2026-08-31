from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Station, Review
from .serializers import StationSerializer, ReviewSerializer


class StationListView(generics.ListAPIView):
    """GET /api/stations/ — mobil ilovadagi StationsAPI.list() uchun."""
    serializer_class = StationSerializer
    queryset = Station.objects.prefetch_related('connectors', 'amenities', 'reviews').all()


class StationDetailView(generics.RetrieveAPIView):
    """GET /api/stations/<id>/ — mobil ilovadagi StationsAPI.getById() uchun."""
    serializer_class = StationSerializer
    queryset = Station.objects.prefetch_related('connectors', 'amenities', 'reviews').all()


class ReviewListView(generics.ListCreateAPIView):
    """GET/POST /api/stations/<station_id>/reviews/ — stansiya sharhlari.
    Bitta foydalanuvchi bitta stansiyaga faqat bitta sharh qoldira oladi;
    qayta yuborilsa mavjud sharh yangilanadi."""
    serializer_class = ReviewSerializer

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
