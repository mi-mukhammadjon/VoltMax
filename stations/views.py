from rest_framework import generics, permissions
from rest_framework.exceptions import ValidationError
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
