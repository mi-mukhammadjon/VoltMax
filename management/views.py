"""Mobil ilova uchun bildirishnomalar API'si.

Panel tomonidagi ko'rinishlar `dashboard` ilovasida — bu yerda faqat
foydalanuvchi o'z xabarlarini o'qiydigan uchta endpoint bor.
"""

from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import UserNotification
from .serializers import UserNotificationSerializer


class NotificationListView(generics.ListAPIView):
    """GET /api/notifications/ — foydalanuvchining xabarlari, yangisi birinchi."""

    serializer_class = UserNotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return UserNotification.objects.filter(
            user=self.request.user
        ).select_related('station')

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        # O'qilmaganlar soni ilovadagi nishon uchun kerak. Sahifalash yoqilgan
        # bo'lsa `response.data` — dict, bo'lmasa ro'yxat; ikkalasi ham
        # qo'llab-quvvatlanadi.
        unread = self.get_queryset().filter(read_at__isnull=True).count()
        if isinstance(response.data, dict):
            response.data['unread'] = unread
        else:
            response.data = {'results': response.data, 'unread': unread}
        return response


class NotificationReadView(APIView):
    """POST /api/notifications/<id>/read/ — bitta xabarni o'qilgan deb belgilaydi."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        notification = get_object_or_404(UserNotification, pk=pk, user=request.user)
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=['read_at'])
        return Response(UserNotificationSerializer(notification).data)


class NotificationReadAllView(APIView):
    """POST /api/notifications/read-all/ — hammasini o'qilgan deb belgilaydi."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        updated = UserNotification.objects.filter(
            user=request.user, read_at__isnull=True
        ).update(read_at=timezone.now())
        return Response({'updated': updated})


class DeviceTokenView(APIView):
    """POST /api/notifications/device/ {token, platform} — push manzilini saqlaydi.

    Ilova har ishga tushganda chaqiradi: token o'zgarishi mumkin (ilova
    qayta o'rnatilganda) va u eskirsa xabar hech qayerga bormaydi.

    DELETE — tokenni o'chiradi (chiqishda). Aks holda telefon boshqa
    odamga o'tsa, unga avvalgi egasining xabarlari kelaverardi.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from accounts.models import DeviceToken

        token = (request.data.get('token') or '').strip()
        if not token:
            return Response({'detail': 'token kerak'}, status=400)

        DeviceToken.register(request.user, token,
                             platform=(request.data.get('platform') or '').lower())
        return Response({'ok': True})

    def delete(self, request):
        from accounts.models import DeviceToken

        token = (request.data.get('token') or request.query_params.get('token') or '').strip()
        if token:
            DeviceToken.objects.filter(user=request.user, token=token).delete()
        return Response(status=204)
