from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import Booking
from .reservations import hold_connector, release_connector
from .serializers import BookingSerializer


class BookingListCreateView(generics.ListCreateAPIView):
    """GET /api/bookings/?status=upcoming|past|cancelled|completed — "Bronlarim" ekrani.
    POST /api/bookings/ — yangi bron yaratish (taxminiy narx avtomatik hisoblanadi)."""
    serializer_class = BookingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Booking.objects.filter(user=self.request.user).select_related('station', 'connector')
        scope = self.request.query_params.get('status')
        if scope == 'upcoming':
            qs = qs.filter(status=Booking.Status.CONFIRMED, scheduled_at__gte=timezone.now())
        elif scope == 'past':
            qs = qs.exclude(status=Booking.Status.CONFIRMED, scheduled_at__gte=timezone.now())
        elif scope == 'cancelled':
            qs = qs.filter(status=Booking.Status.CANCELLED)
        elif scope == 'completed':
            # Tugallangan deb belgilanganlar va vaqti o'tib ketgan tasdiqlanganlar
            qs = qs.filter(
                Q(status=Booking.Status.COMPLETED)
                | Q(status=Booking.Status.CONFIRMED, scheduled_at__lt=timezone.now())
            )
        return qs

    def perform_create(self, serializer):
        booking = serializer.save(user=self.request.user)
        # Ulagich tanlangan bo'lsa, uni qurilmada ham ushlab turamiz —
        # aks holda bron vaqtida boshqa odam kelib foydalanib ketishi mumkin.
        hold_connector(booking)


class BookingCancelView(APIView):
    """POST /api/bookings/<id>/cancel/"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        booking = get_object_or_404(Booking, pk=pk, user=request.user)
        if booking.status == Booking.Status.CONFIRMED:
            booking.status = Booking.Status.CANCELLED
            booking.save(update_fields=['status'])
            release_connector(booking)
        return Response(BookingSerializer(booking).data)
