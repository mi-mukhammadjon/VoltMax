from django.shortcuts import get_object_or_404
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
