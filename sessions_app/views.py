import random

from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from ocpp_gateway import commands as ocpp_commands
from stations.models import Station, Connector
from .models import ChargingSession
from .services import vehicle_snapshot
from .serializers import ChargingSessionSerializer, StartSessionSerializer, SessionHistorySerializer


class StartSessionView(APIView):
    """POST /api/sessions/start/ {stationId, connectorId?} —
    mobil ilovadagi SessionsAPI.start(). Bo'sh ulagichni band qiladi va sessiya boshlaydi.

    Stansiya haqiqiy charger'ga ulangan bo'lsa (Station.ocpp_id bor), sessiya
    bu yerda DARHOL yaratilmaydi — RemoteStartTransaction charger'ga yuboriladi
    va 202 qaytariladi; charger o'zi StartTransaction bilan javob berganda
    (ocpp_gateway/consumers.py) sessiya haqiqiy telemetriya bilan yaratiladi.
    Mobil ilova shunda GET /api/sessions/active/ orqali kutib turadi (poll).
    Hali jismoniy charger ulanmagan stansiyalarda avvalgidek darhol yaratiladi."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = StartSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        station = get_object_or_404(Station, pk=serializer.validated_data['stationId'])

        connector_id = serializer.validated_data.get('connectorId')
        if connector_id:
            connector = get_object_or_404(Connector, pk=connector_id, station=station)
        else:
            connector = station.connectors.filter(status=Connector.Status.AVAILABLE).first()

        if not connector or connector.status != Connector.Status.AVAILABLE:
            return Response({'detail': "Bo'sh ulagich topilmadi"}, status=400)

        # Boshlash qoidalari: balans (minimal chegara bilan) va ish vaqti.
        # Karta bilan ham, ilova bilan ham bir xil qoida amal qiladi
        # (`stations.rules`), sabab esa foydalanuvchiga aynan aytiladi —
        # "boshlanmadi" degan quruq xabar hech narsani tushuntirmaydi.
        from stations.rules import can_start

        reason = can_start(request.user)
        if reason:
            return Response({'detail': reason}, status=400)

        if station.ocpp_id and connector.ocpp_connector_id:
            if not station.is_online:
                return Response({'detail': 'Charger hozir oflayn — birozdan so\'ng qayta urinib ko\'ring'}, status=503)
            ocpp_commands.remote_start_transaction(
                station.ocpp_id, connector.ocpp_connector_id, id_tag=f'APP-{request.user.id}'
            )
            return Response({'pending': True}, status=202)

        # Qaysi mashina zaryadlanmoqda — foydalanuvchining standart mashinasi.
        # Nomi va VIN'i sessiyaga ko'chiriladi, shunda mashina keyin
        # o'chirilsa ham tarix to'liq qoladi.
        vehicle, vehicle_label, vehicle_vin = vehicle_snapshot(request.user)

        session = ChargingSession.objects.create(
            user=request.user, station=station, connector=connector,
            start_percent=random.randint(15, 40),
            power_kw=connector.power_kw, price_per_kwh=station.price_per_kwh,
            connector_label=connector.label,
            vehicle=vehicle, vehicle_label=vehicle_label, vehicle_vin=vehicle_vin,
        )

        connector.status = Connector.Status.CHARGING
        connector.charging_percent = session.start_percent
        connector.save(update_fields=['status', 'charging_percent'])

        return Response(ChargingSessionSerializer(session).data, status=201)


class ActiveSessionView(APIView):
    """GET /api/sessions/active/ — foydalanuvchining hozir davom etayotgan
    sessiyasi (agar bo'lsa). Real charger StartTransaction bilan javob
    berguncha mobil ilova shu endpoint'ni so'rab turadi (poll)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        session = ChargingSession.objects.filter(
            user=request.user, status=ChargingSession.Status.CHARGING
        ).order_by('-started_at').first()
        if session is None:
            return Response(status=204)
        return Response(ChargingSessionSerializer(session).data)


class SessionDetailView(generics.RetrieveAPIView):
    """GET /api/sessions/<id>/ — mobil ilovadagi SessionsAPI.getById()."""
    serializer_class = ChargingSessionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ChargingSession.objects.filter(user=self.request.user)


class SessionListView(generics.ListAPIView):
    """GET /api/sessions/ — HistoryScreen uchun foydalanuvchining o'tgan sessiyalari."""
    serializer_class = SessionHistorySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ChargingSession.objects.filter(user=self.request.user).select_related('station')


class StopSessionView(APIView):
    """POST /api/sessions/<id>/stop/ — mobil ilovadagi SessionsAPI.stop().

    Real charger orqali boshlangan (is_live) sessiya bo'lsa, RemoteStopTransaction
    charger'ga yuboriladi va 202 qaytariladi — charger o'zi StopTransaction bilan
    javob berganda (ocpp_gateway/consumers.py) sessiya haqiqiy yakuniy qiymatlar
    bilan to'xtatiladi. Mock sessiyalar avvalgidek shu yerda darhol to'xtatiladi."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        session = get_object_or_404(ChargingSession, pk=pk, user=request.user)
        if session.status != ChargingSession.Status.CHARGING:
            return Response(ChargingSessionSerializer(session).data)

        if session.is_live and session.station.ocpp_id:
            ocpp_commands.remote_stop_transaction(session.station.ocpp_id, session.id)
            return Response({'pending': True}, status=202)

        session.stop()
        return Response(ChargingSessionSerializer(session).data)


class InsightsView(APIView):
    """GET /api/sessions/insights/ — HistoryScreen'dagi "Smart Insights" kartasi
    uchun: o'rtacha xarajat/energiya va benzin avtomobiliga nisbatan taxminiy
    tejalgan pul/CO2. Benzin taqqoslash — reklama xarakteridagi taxminiy hisob-kitob
    (o'rtacha samaradorlik/narx konstantalari asosida), aniq statistika emas."""
    permission_classes = [permissions.IsAuthenticated]

    # Taxminiy konstantalar — real narxlar/samaradorlik mintaqaga qarab farq qiladi
    KM_PER_KWH = 6
    PETROL_L_PER_100KM = 8
    PETROL_PRICE_PER_L = 13000
    CO2_KG_PER_KM = 0.12

    def get(self, request):
        finished = ChargingSession.objects.filter(
            user=request.user, status__in=[ChargingSession.Status.STOPPED, ChargingSession.Status.COMPLETED]
        )
        total_sessions = finished.count()
        total_kwh = sum(s.kwh_charged for s in finished)
        total_spent = sum(s.cost_so_far for s in finished)

        estimated_km = total_kwh * self.KM_PER_KWH
        petrol_equivalent_cost = round(estimated_km / 100 * self.PETROL_L_PER_100KM * self.PETROL_PRICE_PER_L)

        return Response({
            'totalSessions': total_sessions,
            'totalKwh': round(total_kwh, 1),
            'totalSpent': total_spent,
            'avgCostPerSession': round(total_spent / total_sessions) if total_sessions else 0,
            'avgKwhPerSession': round(total_kwh / total_sessions, 1) if total_sessions else 0,
            'savedVsGasoline': max(0, petrol_equivalent_cost - total_spent),
            'co2SavedKg': round(estimated_km * self.CO2_KG_PER_KM),
        })
