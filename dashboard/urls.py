from django.urls import path

from . import (
    views, views_device as dev, views_maintenance as mt,
    views_management as m, views_rfid as rf,
)

app_name = 'dashboard'

urlpatterns = [
    # ── Auth ────────────────────────────────────────────────
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # ── Bosh sahifa ─────────────────────────────────────────
    path('', views.home, name='home'),

    # ── Stansiyalar ─────────────────────────────────────────
    path('stations/', views.stations_list, name='stations'),
    path('stations/health/', m.stations_health, name='stations_health'),

    # ── Profilaktika: nosozliklar bilan ishlash ─────────────
    path('maintenance/', mt.maintenance, name='maintenance'),
    path('maintenance/sync/', mt.maintenance_sync, name='maintenance_sync'),
    path('maintenance/open/', mt.maintenance_open, name='maintenance_open'),
    path('maintenance/notify-all/', mt.maintenance_notify_all, name='maintenance_notify_all'),
    path('maintenance/<int:pk>/resolve/', mt.maintenance_resolve, name='maintenance_resolve'),
    path('maintenance/<int:pk>/notify/', mt.maintenance_notify, name='maintenance_notify'),
    path('maintenance/<int:pk>/recipients/', mt.maintenance_recipients, name='maintenance_recipients'),
    path('stations/sync/', views.sync_status, name='sync_status'),
    path('geocode/', m.geocode, name='geocode'),
    path('stations/new/', views.station_form_view, name='station_new'),
    path('stations/<int:pk>/', views.station_detail, name='station_detail'),
    path('stations/<int:pk>/edit/', views.station_form_view, name='station_edit'),
    path('stations/<int:pk>/delete/', views.station_delete, name='station_delete'),
    path('stations/<int:pk>/connectors/<int:connector_pk>/edit/', views.connector_edit, name='connector_edit'),
    path('stations/<int:pk>/connectors/<int:connector_pk>/toggle-service/', views.connector_toggle_service, name='connector_toggle_service'),
    path('stations/<int:pk>/connectors/<int:connector_pk>/delete/', views.connector_delete, name='connector_delete'),
    path('stations/<int:pk>/connectors/<int:connector_pk>/remote-start/', views.connector_remote_start, name='connector_remote_start'),
    path('stations/<int:pk>/connectors/<int:connector_pk>/remote-stop/', views.connector_remote_stop, name='connector_remote_stop'),
    path('stations/<int:pk>/amenities/<int:amenity_pk>/delete/', views.amenity_delete, name='amenity_delete'),
    path('stations/<int:pk>/assign-partner/', m.station_assign_partner, name='station_assign_partner'),

    # ── Qurilma bilan bevosita ishlash (OCPP) ───────────────
    path('stations/<int:pk>/device/read-config/', dev.device_read_config, name='device_read_config'),
    path('stations/<int:pk>/device/write-config/', dev.device_write_config, name='device_write_config'),
    path('stations/<int:pk>/device/reset/', dev.device_reset, name='device_reset'),
    path('stations/<int:pk>/device/clear-cache/', dev.device_clear_cache, name='device_clear_cache'),
    path('stations/<int:pk>/device/firmware/', dev.device_update_firmware, name='device_update_firmware'),
    path('stations/<int:pk>/device/diagnostics/', dev.device_get_diagnostics, name='device_get_diagnostics'),
    path('stations/<int:pk>/device/<int:connector_pk>/power-limit/', dev.device_power_limit, name='device_power_limit'),
    path('stations/<int:pk>/sync/', views.station_sync, name='station_sync'),

    # ── Sessiyalar ──────────────────────────────────────────
    path('sessions/', views.sessions_list, name='sessions'),
    path('sessions/<int:pk>/', views.session_detail, name='session_detail'),
    path('sessions/<int:pk>/stop/', views.session_force_stop, name='session_force_stop'),

    # ── Foydalanuvchilar ────────────────────────────────────
    path('users/', views.users_list, name='users'),
    path('users/<int:pk>/', views.user_detail, name='user_detail'),
    path('users/<int:pk>/toggle-active/', views.user_toggle_active, name='user_toggle_active'),

    # ── Hamyonlar va to'lovlar ──────────────────────────────
    path('wallets/', m.wallets_list, name='wallets'),
    path('wallets/<int:pk>/', m.wallet_detail, name='wallet_detail'),
    path('payments/', views.transactions_list, name='transactions'),

    # ── Sharhlar ────────────────────────────────────────────
    path('reviews/', m.reviews_list, name='reviews'),
    path('reviews/<int:pk>/delete/', m.review_delete, name='review_delete'),

    # ── Hisobotlar ──────────────────────────────────────────
    path('reports/revenue/', m.reports_revenue, name='reports_revenue'),
    path('reports/usage/', m.reports_usage, name='reports_usage'),

    # ── Aksiyalar ───────────────────────────────────────────
    path('offers/', m.offers_list, name='offers'),
    path('offers/new/', m.offer_form_view, name='offer_new'),
    path('offers/<int:pk>/', m.offer_detail, name='offer_detail'),
    path('offers/<int:pk>/edit/', m.offer_form_view, name='offer_edit'),
    path('offers/<int:pk>/delete/', m.offer_delete, name='offer_delete'),

    # ── Hamkorlar ───────────────────────────────────────────
    path('partners/', m.partners_list, name='partners'),
    path('partners/new/', m.partner_form_view, name='partner_new'),
    path('partners/<int:pk>/', m.partner_detail, name='partner_detail'),
    path('partners/<int:pk>/edit/', m.partner_form_view, name='partner_edit'),
    path('partners/<int:pk>/delete/', m.partner_delete, name='partner_delete'),
    path('partners/<int:pk>/attach-stations/', m.partner_attach_stations, name='partner_attach_stations'),
    path('partners/<int:pk>/detach/<int:station_pk>/', m.partner_detach_station, name='partner_detach_station'),

    # ── Xodimlar ────────────────────────────────────────────
    path('managers/', m.managers_list, name='managers'),
    path('managers/new/', m.manager_form_view, name='manager_create'),
    path('managers/<int:pk>/', m.staff_detail, name='manager_detail'),
    path('managers/<int:pk>/edit/', m.manager_form_view, name='manager_edit'),

    path('admins/', m.admins_list, name='admins'),
    path('admins/new/', m.admin_form_view, name='admin_create'),
    path('admins/<int:pk>/', m.staff_detail, name='admin_detail'),
    path('admins/<int:pk>/edit/', m.admin_form_view, name='admin_edit'),

    path('staff/<int:pk>/delete/', m.staff_delete, name='staff_delete'),

    # ── Rollar ──────────────────────────────────────────────
    path('roles/', m.roles_list, name='roles'),
    path('roles/new/', m.role_form_view, name='role_new'),
    path('roles/<int:pk>/edit/', m.role_form_view, name='role_edit'),
    path('roles/<int:pk>/delete/', m.role_delete, name='role_delete'),

    # ── Kontent ─────────────────────────────────────────────
    path('content/banners/', m.content_banners, name='content_banners'),
    path('content/banners/new/', m.banner_form_view, name='banner_new'),
    path('content/banners/<int:pk>/edit/', m.banner_form_view, name='banner_edit'),
    path('content/banners/<int:pk>/delete/', m.banner_delete, name='banner_delete'),

    path('content/faq/', m.content_faq, name='content_faq'),
    path('content/faq/new/', m.faq_form_view, name='faq_new'),
    path('content/faq/<int:pk>/edit/', m.faq_form_view, name='faq_edit'),
    path('content/faq/<int:pk>/delete/', m.faq_delete, name='faq_delete'),

    path('content/pages/', m.content_pages, name='content_pages'),
    path('content/pages/<str:slug>/', m.page_form_view, name='page_edit'),

    # ── Sozlamalar ──────────────────────────────────────────
    path('settings/', m.settings_general, name='settings'),
    path('settings/general/', m.settings_general, name='settings_general'),
    path('settings/payment/', m.settings_payment, name='settings_payment'),
    path('settings/notification/', m.settings_notification, name='settings_notification'),
    path('settings/security/', m.settings_security, name='settings_security'),
    path('settings/org/', m.settings_org, name='settings_org'),
    path('settings/session/', m.settings_session, name='settings_session'),
    path('settings/search/', m.settings_search, name='settings_search'),
    # To'lov tizimlari — ro'yxat bazada, kodda emas
    path('settings/providers/', m.settings_providers, name='settings_providers'),
    path('settings/providers/new/', m.provider_form_view, name='provider_new'),
    path('settings/providers/<int:pk>/', m.provider_form_view, name='provider_edit'),
    path('settings/providers/<int:pk>/toggle/', m.provider_toggle, name='provider_toggle'),
    path('settings/providers/<int:pk>/delete/', m.provider_delete, name='provider_delete'),
    # Bildirishnoma matnlari — panelda tahrirlanadi
    path('settings/notifications/<int:pk>/', m.notification_template_edit,
         name='notification_template_edit'),
    path('settings/notifications/reset/', m.notification_templates_reset,
         name='notification_templates_reset'),
    path('settings/contract/', m.settings_contract, name='settings_contract'),
    # Shartnoma shartlari — sozlamalar tabining ichida boshqariladi
    path('settings/contract/sections/new/', m.contract_section_form_view,
         name='contract_section_new'),
    path('settings/contract/sections/<int:pk>/', m.contract_section_form_view,
         name='contract_section_edit'),
    path('settings/contract/sections/<int:pk>/delete/', m.contract_section_delete,
         name='contract_section_delete'),
    path('settings/contract/sections/<int:pk>/move/', m.contract_section_move,
         name='contract_section_move'),
    path('settings/contract/reset/', m.contract_sections_reset,
         name='contract_sections_reset'),
    path('settings/contract/preview/', m.contract_preview, name='contract_preview'),
    # Bayram kunlari — kalendarda ajratib ko'rsatiladi
    path('settings/holiday/', m.settings_holiday, name='settings_holiday'),
    path('settings/holiday/sync/', m.holidays_sync, name='holidays_sync'),
    path('settings/holiday/add/', m.holiday_add, name='holiday_add'),
    path('settings/holiday/<int:pk>/delete/', m.holiday_delete, name='holiday_delete'),
    path('holidays.json', m.holidays_json, name='holidays_json'),

    # ── RFID kartalar ───────────────────────────────────────
    path('rfid/', rf.rfid_cards, name='rfid_cards'),
    path('rfid/new/', rf.rfid_card_create, name='rfid_card_create'),
    path('rfid/push/', rf.rfid_push, name='rfid_push'),
    path('rfid/<int:pk>/status/', rf.rfid_card_status, name='rfid_card_status'),
    path('rfid/bulk/', rf.rfid_bulk, name='rfid_bulk'),
    path('rfid/<int:pk>/', rf.rfid_card_detail, name='rfid_card_detail'),
    path('rfid/<int:pk>/extend/', rf.rfid_card_extend, name='rfid_card_extend'),
    path('rfid/<int:pk>/delete/', rf.rfid_card_delete, name='rfid_card_delete'),

    # ── Korporativ mijozlar ─────────────────────────────────
    path('companies/', rf.companies, name='companies'),
    path('companies/new/', rf.company_form_view, name='company_new'),
    path('companies/<int:pk>/', rf.company_detail, name='company_detail'),
    path('companies/<int:pk>/edit/', rf.company_form_view, name='company_edit'),
    # Batafsil sahifadagi bo'limni saqlash (nomi: basics | requisites)
    path('companies/<int:pk>/edit/<slug:section>/', rf.company_section_edit,
         name='company_section_edit'),
    path('companies/<int:pk>/topup/', rf.company_topup, name='company_topup'),
    path('companies/<int:pk>/contract/', rf.company_contract, name='company_contract'),
    # To'lov hisoblari — korporativ mijoz bank orqali to'laydi
    path('companies/<int:pk>/invoices/new/', rf.company_invoice_create,
         name='company_invoice_create'),
    path('invoices/<int:pk>/paid/', rf.company_invoice_paid, name='company_invoice_paid'),
    path('invoices/<int:pk>/cancel/', rf.company_invoice_cancel, name='company_invoice_cancel'),
    path('invoices/<int:pk>/document/', rf.company_invoice_document,
         name='company_invoice_document'),

    # ── Profil ──────────────────────────────────────────────
    path('profile/', m.profile, name='profile'),

    # ── OTP ─────────────────────────────────────────────────
    path('otp/', views.otp_list, name='otp_list'),
]
