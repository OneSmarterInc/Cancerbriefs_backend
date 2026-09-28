from django.urls import path
from . import views

urlpatterns = [
    # --- PUBLIC CORE & AUTH ENDPOINTS ---
    path('health/', views.health, name='health'),
    path('news/', views.news, name='news'),
    path('register/', views.register, name='register'),
    path('login/', views.login, name='login'),
    path('logout/', views.logout, name='logout'),
    
    # --- 2FA ENDPOINTS ---
    path('setup-2fa/', views.setup_2fa, name='setup_2fa'),
    path('verify-2fa/', views.verify_2fa, name='verify_2fa'),
    
    # --- ARTICLE INTERACTIONS ---
    path('news/<int:article_id>/toggle/', views.toggle_article, name='toggle_article'),
    path('news/<int:article_id>/query/', views.submit_query, name='submit_query'),
    
    # --- NEWSLETTER & FEEDBACK ---
    path('subscribe/', views.subscribe_newsletter, name='subscribe_newsletter'),
    path('unsubscribe/', views.unsubscribe_email, name='unsubscribe_email'),
    path('audio/', views.generate_audio, name='generate_audio'),
    path("social/", views.get_social_links, name="get_social_links"),
    path("rss-feeds/", views.get_active_rss_feeds, name="get_active_rss_feeds"),
    path('blogs/', views.get_blogs, name='get_blogs'),
    path('books/', views.get_books, name='get_books'),

    # --- ADMINISTRATION MANAGEMENT ENDPOINTS ---
    path('administration/queries/', views.get_queries, name='get_queries'),
    path('administration/queries/<int:query_id>/toggle/', views.toggle_query_status, name='toggle_query_status'),
    path('administration/subscribers/', views.manage_subscribers, name='manage_subscribers'),
    path('administration/subscribers/<int:sub_id>/toggle/', views.toggle_subscriber, name='toggle_subscriber'),
    path('administration/subscribers/<int:sub_id>/delete/', views.delete_subscriber, name='delete_subscriber'),
    path('administration/smtp/', views.manage_smtp, name='manage_smtp'),
    path('administration/smtp/test/', views.send_test_email, name='send_test_email'),
    path('administration/smtp/blast/', views.send_daily_blast, name='send_daily_blast'),
    path('administration/feeds/', views.manage_rss_feeds, name='manage_rss_feeds'),
    path('administration/feeds/<int:feed_id>/', views.modify_rss_feed, name='modify_rss_feed'),
    path("administration/social/", views.admin_social_links, name="admin_social_links"),
    path("administration/blogs/", views.admin_manage_blogs, name="admin_manage_blogs"),
    path("administration/blogs/<int:blog_id>/", views.admin_modify_blog, name="admin_modify_blog"),
    path('administration/books/', views.admin_manage_books, name='admin_manage_books'),
    path('administration/books/<int:book_id>/', views.admin_modify_book, name='admin_modify_book'),

    path('volunteer/', views.submit_volunteer),
    path('admin/volunteers/', views.admin_volunteers),
    path('admin/volunteers/<int:app_id>/', views.admin_volunteers),

    path('positions/', views.get_positions),
    path('admin/positions/', views.admin_positions),
    path('admin/positions/<int:pos_id>/', views.admin_positions),

    # --- PASSWORD RESET ENDPOINTS ---
    path('password-reset/', views.password_reset_request, name='password_reset_request'),
    path('password-reset-confirm/', views.password_reset_confirm, name='password_reset_confirm'),

]