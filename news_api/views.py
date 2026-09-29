import io
import base64
import datetime
import asyncio
import qrcode
import pyotp
import edge_tts
import logging
import uuid
import email.utils

from django.conf import settings
from django.shortcuts import render
from django.http import HttpResponse
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password

from rest_framework.decorators import api_view, permission_classes, authentication_classes, throttle_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAdminUser, AllowAny
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from rest_framework.throttling import AnonRateThrottle

from django.db import models
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .models import OpenPosition, VolunteerApplication
from .models import Article, SocialMediaConfig, RSSFeed
from .services import get_stored_news

import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from .models import SMTPConfig
from django.core.mail.backends.smtp import EmailBackend
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)

# --- UPDATED: Live Production URLs ---
FRONTEND_URL = "https://cancerbriefs-frontend.vercel.app"  # Explicitly matches your EC2 public IP
BACKEND_URL = "cancerbriefs.onesmarter.com"

IMAGE_URL = "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1200&q=80"

# --- SECURITY: STRICT THROTTLE ---
class SensitiveActionThrottle(AnonRateThrottle):
    rate = '5/min'

# --- SECURITY: HTTPONLY COOKIE AUTHENTICATION ---
class CookieTokenAuthentication(TokenAuthentication):
    """Custom authentication class that securely extracts the DRF token from an HttpOnly cookie."""
    def authenticate(self, request):
        token = request.COOKIES.get('auth_token')
        if not token:
            return super().authenticate(request)
        return self.authenticate_credentials(token)


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})

@api_view(["GET"])
def news(request):
    articles = Article.objects.exclude(ai_headline="")
    data = []

    for article in articles:
        # Safely get professor_id, defaulting to 1 if it somehow fails
        prof_id = getattr(article, 'professor_id', 1) 
        
        data.append({
            "id": article.id,
            "source": article.source,
            "category": article.category,
            "title": article.ai_headline or article.title,
            "original_title": article.title,
            "summary": article.summary,
            "link": article.link,
            "published": article.published,
            "is_active": article.is_active,
            "image_url": IMAGE_URL,
            "professor_id": prof_id # <-- ADDED THIS LINE TO SEND DATA TO FRONTEND
        })

    # --- ROBUST DATE SORTING ---
    def extract_date(item):
        pub_str = item.get("published", "")
        if not pub_str:
            return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
        
        try:
            dt = email.utils.parsedate_to_datetime(pub_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt
        except Exception:
            pass
            
        try:
            dt = datetime.datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt
        except Exception:
            pass
            
        return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

    data.sort(key=extract_date, reverse=True)

    total_sources = RSSFeed.objects.filter(is_active=True).count()

    return Response({
        "count": len(data),
        "total_sources": total_sources,
        "articles": data
    })

@api_view(["POST"])
@throttle_classes([SensitiveActionThrottle])
def register(request):
    username = request.data.get("username", "").strip()
    email = request.data.get("email", "").strip()
    password = request.data.get("password", "")

    if not username or not email or not password:
        return Response({"error": "Username, email and password are required."}, status=400)

    try:
        validate_password(password)
    except ValidationError as exc:
        return Response({"error": " ".join(exc.messages)}, status=400)

    if User.objects.filter(username=username).exists():
        return Response({"error": "Username already exists."}, status=400)

    if User.objects.filter(email=email).exists():
        return Response({"error": "Email already exists."}, status=400)

    user = User.objects.create_user(username=username, email=email, password=password)
    token, created = Token.objects.get_or_create(user=user)

    response = Response({
        "message": "Registration successful.",
        "user": {"id": user.id, "username": user.username, "email": user.email}
    }, status=201)
    
    response.set_cookie(
        'auth_token', token.key, httponly=True, 
        secure=not settings.DEBUG, samesite='lax', max_age=43200
    )
    return response

@api_view(["POST"])
@throttle_classes([SensitiveActionThrottle])
def login(request):
    username = request.data.get("username", "").strip()
    password = request.data.get("password", "")

    if not username or not password:
        return Response({"error": "Username and password are required."}, status=400)

    user = authenticate(username=username, password=password)
    if user is None:
        return Response({"error": "Invalid username or password."}, status=401)

    is_admin = user.is_staff or user.is_superuser
    if not is_admin:
        return Response({"error": "Access denied. Admin privileges required."}, status=403)

    from .models import Admin2FA
    two_fa, created = Admin2FA.objects.get_or_create(user=user)

    challenge_id = str(uuid.uuid4())
    cache.set(f"mfa_{challenge_id}", user.id, timeout=300)

    if not two_fa.is_enabled:
        return Response({"status": "setup_required", "challenge_id": challenge_id})
    else:
        return Response({"status": "mfa_required", "challenge_id": challenge_id})

@api_view(["POST"])
@throttle_classes([SensitiveActionThrottle])
def setup_2fa(request):
    challenge_id = request.data.get("challenge_id")
    if not challenge_id:
        return Response({"error": "Challenge ID missing."}, status=400)
        
    user_id = cache.get(f"mfa_{challenge_id}")
    if not user_id:
        return Response({"error": "Invalid or expired challenge."}, status=401)
        
    try:
        user = User.objects.get(id=user_id)
        from .models import Admin2FA
        two_fa, _ = Admin2FA.objects.get_or_create(user=user)
        
        if two_fa.is_enabled:
            return Response({"error": "2FA is already configured. Please use a recovery procedure to reset."}, status=403)
        
        secret = pyotp.random_base32()
        two_fa.totp_secret = secret
        two_fa.save()
        
        totp_url = pyotp.totp.TOTP(secret).provisioning_uri(
            name=user.email or user.username, 
            issuer_name="The Aggregate Desk"
        )
        
        qr = qrcode.make(totp_url)
        buffer = io.BytesIO()
        qr.save(buffer, format="PNG")
        qr_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        return Response({
            "secret": secret,
            "qr_image": f"data:image/png;base64,{qr_base64}"
        })
    except Exception:
        logger.exception("Operation failed")
        return Response({"error": "Unable to process request."}, status=500)

@api_view(["POST"])
@throttle_classes([SensitiveActionThrottle])
def verify_2fa(request):
    challenge_id = request.data.get("challenge_id")
    code = request.data.get("code", "").strip()
    
    if not challenge_id:
        return Response({"error": "Challenge ID missing."}, status=400)
        
    user_id = cache.get(f"mfa_{challenge_id}")
    if not user_id:
        return Response({"error": "Invalid or expired challenge."}, status=401)
    
    try:
        user = User.objects.get(id=user_id)
        from .models import Admin2FA
        two_fa = Admin2FA.objects.get(user=user)
        
        totp = pyotp.TOTP(two_fa.totp_secret)
        if totp.verify(code, valid_window=1):
            two_fa.is_enabled = True
            two_fa.save()
            
            cache.delete(f"mfa_{challenge_id}")
            
            Token.objects.filter(user=user).delete()
            token = Token.objects.create(user=user)
            
            response = Response({
                "message": "Login successful.",
                "user": {"id": user.id, "username": user.username, "email": user.email, "is_admin": True}
            })
            
            response.set_cookie(
            "auth_token",
            token.key,
            httponly=True,
            secure=True,
            samesite="None",
            max_age=43200
            )
            return response
        else:
            return Response({"error": "Invalid 2FA code."}, status=401)
    except Exception:
        logger.exception("Operation failed")
        return Response({"error": "Unable to process request."}, status=500)

@api_view(["POST"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def logout(request):
    try:
        request.user.auth_token.delete()
    except Exception:
        pass
    
    response = Response({"status": "success", "message": "Successfully logged out."})
    response.delete_cookie('auth_token')
    return response

@api_view(["POST"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def toggle_article(request, article_id):
    try:
        article = Article.objects.get(id=article_id)
        article.is_active = not article.is_active
        article.save()
        return Response({"status": "success", "is_active": article.is_active})
    except Exception:
        logger.exception("Operation failed")
        return Response({"error": "Unable to process request."}, status=500)

@api_view(["POST"])
def submit_query(request, article_id):
    try:
        from .models import ArticleQuery
        article = Article.objects.get(id=article_id)
        text = request.data.get("query_text", "").strip()
        
        if not text:
            return Response({"error": "Query text cannot be empty."}, status=400)
            
        ArticleQuery.objects.create(article=article, query_text=text)
        return Response({"status": "success", "message": "Query submitted."})
    except Exception:
        logger.exception("Operation failed")
        return Response({"error": "Unable to process request."}, status=500)

@api_view(["GET"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def get_queries(request):
    from .models import ArticleQuery
    queries = ArticleQuery.objects.all()
    data = []
    for q in queries:
        data.append({
            "id": q.id,
            "article_id": q.article.id,
            "article_title": q.article.title,
            "article_is_active": q.article.is_active,
            "query_text": q.query_text,
            "is_resolved": q.is_resolved,
            "created_at": q.created_at.strftime("%Y-%m-%d %H:%M")
        })
    return Response({"queries": data})

@api_view(["POST"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def toggle_query_status(request, query_id):
    try:
        from .models import ArticleQuery
        query = ArticleQuery.objects.get(id=query_id)
        query.is_resolved = not query.is_resolved
        query.save()
        return Response({"status": "success"})
    except Exception:
        logger.exception("Operation failed")
        return Response({"error": "Unable to process request."}, status=500)

@api_view(["GET", "POST"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def manage_subscribers(request):
    from .models import Subscriber
    
    if request.method == "POST":
        email = request.data.get("email", "").strip()
        if not email: return Response({"error": "Email is required"}, status=400)
            
        sub, created = Subscriber.objects.get_or_create(email=email)
        if not created:
            sub.is_active = True
            sub.save()
            
        return Response({
            "status": "success",
            "subscriber": {
                "id": sub.id, "email": sub.email, 
                "subscribed_at": sub.subscribed_at.strftime("%Y-%m-%d %H:%M"),
                "emails_received": sub.emails_received, "is_active": sub.is_active
            }
        })
    
    subs = Subscriber.objects.all()
    data = [{"id": s.id, "email": s.email, "subscribed_at": s.subscribed_at.strftime("%Y-%m-%d %H:%M"), "emails_received": s.emails_received, "is_active": s.is_active} for s in subs]
    return Response({"subscribers": data})

@api_view(["POST"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def toggle_subscriber(request, sub_id):
    try:
        from .models import Subscriber
        sub = Subscriber.objects.get(id=sub_id)
        sub.is_active = not sub.is_active
        sub.save()
        return Response({"status": "success", "is_active": sub.is_active})
    except Exception:
        logger.exception("Operation failed")
        return Response({"error": "Unable to process request."}, status=500)

@api_view(["DELETE"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def delete_subscriber(request, sub_id):
    try:
        from .models import Subscriber
        sub = Subscriber.objects.get(id=sub_id)
        sub.delete()
        return Response({"status": "success", "message": "Subscriber permanently deleted."})
    except Exception:
        logger.exception("Operation failed")
        return Response({"error": "Unable to process request."}, status=500)

@api_view(["GET", "POST"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def manage_rss_feeds(request):
    if request.method == "POST":
        name = request.data.get("name", "").strip()
        url = request.data.get("url", "").strip()
        category = request.data.get("category", "").strip()
        
        if not name or not url or not category:
            return Response({"error": "Name, URL, and category are required."}, status=400)
            
        feed, created = RSSFeed.objects.get_or_create(url=url, defaults={"name": name, "category": category})
        if not created:
            feed.name = name
            feed.category = category
            feed.is_active = True
            feed.save()
            
        return Response({
            "status": "success",
            "feed": {"id": feed.id, "name": feed.name, "url": feed.url, "category": feed.category, "is_active": feed.is_active}
        })
    
    feeds = RSSFeed.objects.all().order_by("-id")
    data = [{"id": f.id, "name": f.name, "url": f.url, "category": f.category, "is_active": f.is_active} for f in feeds]
    return Response({"feeds": data})

@api_view(["POST", "DELETE"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def modify_rss_feed(request, feed_id):
    try:
        feed = RSSFeed.objects.get(id=feed_id)
        if request.method == "DELETE":
            feed.delete()
            return Response({"status": "success", "message": "Feed deleted."})
        else:
            feed.is_active = not feed.is_active
            feed.save()
            return Response({"status": "success", "is_active": feed.is_active})
    except RSSFeed.DoesNotExist:
        return Response({"error": "Feed not found."}, status=404)

@api_view(["GET"])
def unsubscribe_email(request):
    token = request.GET.get("token")

    if not token:
        return HttpResponse("Invalid request.", status=400)

    try:
        data = signing.loads(token)
        sub_id = data.get("subscriber_id")
    except signing.BadSignature:
        return HttpResponse("Invalid or expired unsubscribe link.", status=400)

    from .models import Subscriber
    sub = Subscriber.objects.filter(id=sub_id).first()
    
    if not sub:
        return HttpResponse("Subscriber not found.", status=404)

    sub.is_active = False
    sub.save()

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Unsubscribed</title>
        <style>
            body {{ font-family: Arial, sans-serif; background-color: #F3EEE3; color: #161412; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
            .container {{ text-align: center; padding: 40px; border: 2px solid #161412; background-color: #fff; max-width: 400px; }}
            h2 {{ font-family: Georgia, serif; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Unsubscribed Successfully</h2>
            <p><strong>support@onesmarter.com</strong> has been removed from the Cyberbriefs mailing list.</p>
            <p>You will no longer receive automated daily briefings.</p>
        </div>
    </body>
    </html>
    """
    
    return HttpResponse(html_content)

def generate_email_html(articles, subscriber):
    token = signing.dumps({"subscriber_id": subscriber.id})
    backend_url = getattr(settings, "BACKEND_URL", FRONTEND_URL)
    unsubscribe_link = f"{backend_url}/api/unsubscribe/?token={token}"
    
    current_date = datetime.datetime.now().strftime("%m-%d-%Y")
    
    html = f"""<!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
    </head>
    <body style="margin: 0; padding: 0; background-color: #ffffff;">
        <div style="font-family: Arial, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background-color: #ffffff; color: #333333;">
            <h2 style="font-size: 16px; color: #000000; margin: 0 0 10px 0; font-weight: bold;">Cyberbriefs Newsletter</h2>
            <hr style="border: 0; border-top: 1px solid #cccccc; margin-bottom: 15px;" />
            <p style="font-size: 11px; line-height: 1.5; color: #555555; margin-bottom: 15px;">
                Here are your latest curated cybersecurity updates, compiled directly from our intelligence desk.
            </p>
            <p style="font-size: 11px; color: #555555; margin-bottom: 30px;">Summary Generated at {current_date}</p>
    """
    
    if not articles:
        html += "<p style='color: red;'><strong>Notice:</strong> No active articles were found in the database.</p>"
    else:
        for a in articles:
            title = a.ai_headline or a.title
            summary = a.summary or "Summary unavailable."
            
            # Appends &sub=true to bypass frontend subscribe popups
            article_link = f"{FRONTEND_URL}/?article_id={a.id}&sub=true"
            
            # --- EXACT WEBSITE MATCH: Pulls Proff_{id}.png dynamically ---
            prof_id = getattr(a, 'professor_id', 1) or 1
            img_url = f"{FRONTEND_URL}/images/Proff_{prof_id}.png"
            
            if len(summary) > 230:
                summary = summary[:227] + "..."
            
            html += f"""
            <div style="margin-bottom: 15px; background-color: #F8F9FA; border-radius: 8px; border: 1px solid #EBE4D5;">
                <a href="{article_link}" target="_blank" style="text-decoration: none; color: inherit; display: block; padding: 15px;">
                    <table width="100%" cellpadding="0" cellspacing="0" border="0">
                        <tr>
                            <td width="115" valign="top" style="padding-right: 15px;">
                                <img src="{img_url}" width="100" height="100" style="display: block; border-radius: 8px; object-fit: cover; width: 100px; height: 100px; border: none;" alt="Professor Avatar" />
                            </td>
                            <td valign="top">
                                <h3 style="margin: 0 0 8px 0; font-size: 14px; font-family: Arial, sans-serif; color: #000000; font-weight: bold;">{title}</h3>
                                <p style="margin: 0; font-size: 12px; color: #333333; line-height: 1.4; font-family: Arial, sans-serif;">{summary}</p>
                            </td>
                        </tr>
                    </table>
                </a>
            </div>
            """
            
    html += f"""
            <div style="text-align: center; margin-top: 40px; padding-top: 20px; border-top: 1px solid #cccccc;">
                <p style="color: #777777; font-size: 11px; margin-bottom: 15px;">You are receiving this automated dispatch because you subscribed.</p>
                <a href="{unsubscribe_link}" style="display: inline-block; padding: 10px 20px; background-color: #000000; color: #ffffff; font-size: 11px; font-weight: bold; text-decoration: none; border-radius: 4px; text-transform: uppercase;">Unsubscribe</a>
            </div>
        </div>
    </body>
    </html>
    """
    return html

@api_view(["GET", "POST"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def manage_smtp(request):
    from .models import SMTPConfig
    if request.method == "POST":
        config = SMTPConfig.objects.first() or SMTPConfig()
        config.name = request.data.get("name", "")
        config.email = request.data.get("email", "")
        config.reply_to = request.data.get("reply_to", "")
        config.host = request.data.get("host", "")
        config.port = int(request.data.get("port", 587))
        config.username = request.data.get("username", "")
        config.security_protocol = request.data.get("security_protocol", "TLS")
        config.daily_send_time = request.data.get("daily_send_time", "08:00")
        if request.data.get("password"): config.password = request.data.get("password")
        config.save()
        return Response({"status": "success"})
    config = SMTPConfig.objects.first()
    if config: return Response({"name": config.name, "email": config.email, "reply_to": config.reply_to, "host": config.host, "port": config.port, "username": config.username, "security_protocol": config.security_protocol, "daily_send_time": config.daily_send_time, "password": "" })
    return Response({})

@api_view(["POST"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def send_test_email(request):
    try:
        from .models import SMTPConfig
        from django.core.mail import EmailMultiAlternatives
        from django.core.mail.backends.smtp import EmailBackend
        recipient = request.data.get("email", "").strip()
        config = SMTPConfig.objects.first()
        backend = EmailBackend(host=config.host, port=config.port, username=config.username or config.email, password=config.password, use_tls=(config.security_protocol == 'TLS'), use_ssl=(config.security_protocol == 'SSL'))
        msg = EmailMultiAlternatives(subject='Test Email', body='Working!', from_email=f"{config.name} <{config.email}>", to=[recipient], connection=backend)
        msg.send()
        return Response({"status": "success"})
    except Exception:
        logger.exception("Operation failed")
        return Response({"error": "Unable to process request."}, status=500)

@api_view(["POST"])
def subscribe_newsletter(request):
    try:
        from .models import Subscriber
        recipient = request.data.get("email", "").strip()
        if not recipient: 
            return Response({"error": "Email is required."}, status=400)
            
        sub = Subscriber.objects.filter(email=recipient).first()
        if sub:
            if sub.is_active:
                return Response({"status": "already_subscribed", "message": "Email is already on the list."})
            else:
                sub.is_active = True
                sub.save()
                return Response({"status": "success", "message": "Subscription reactivated!"})
        
        Subscriber.objects.create(email=recipient, is_active=True)
        return Response({"status": "success", "message": "Subscription added!"})
    except Exception:
        logger.exception("Operation failed")
        return Response({"error": "Unable to process request."}, status=500)

def process_mass_blast():
    try:
        from .models import SMTPConfig, Article, Subscriber
        from django.core.mail import EmailMultiAlternatives
        from django.core.mail.backends.smtp import EmailBackend
        
        config = SMTPConfig.objects.first()
        subscribers = Subscriber.objects.filter(is_active=True)
        if not subscribers: 
            return False, "No active subscribers found."
            
        # --- ENSURES LATEST 5 UPDATED ARTICLES ARE FETCHED ---
        latest_articles = list(Article.objects.filter(is_active=True).exclude(ai_headline="").order_by('-id')[:5])
        
        backend = EmailBackend(
            host=config.host, 
            port=config.port, 
            username=config.username or config.email, 
            password=config.password, 
            use_tls=(config.security_protocol == 'TLS'), 
            use_ssl=(config.security_protocol == 'SSL')
        )
        
        sent_count = 0
        for sub in subscribers:
            try:
                user_html = generate_email_html(latest_articles, sub)
                msg = EmailMultiAlternatives(
                    subject='Cyberbriefs Daily Intelligence',
                    body='Please view this email in an HTML-compatible client.',
                    from_email=f"{config.name or 'Cyberbriefs'} <{config.email}>",
                    to=[sub.email],
                    reply_to=[config.reply_to] if config.reply_to else None,
                    connection=backend
                )
                msg.attach_alternative(user_html, "text/html")
                msg.send()
                sub.emails_received += 1
                sub.save()
                sent_count += 1
            except Exception:
                logger.exception(f"Failed to send to {sub.email}")
        return True, f"Sent {sent_count} emails!"
    except Exception:
        logger.exception("Operation failed")
        return False, "Unable to process request."

@api_view(["POST"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def send_daily_blast(request):
    success, message = process_mass_blast()
    if success: 
        return Response({"status": "success", "message": message})
    else: 
        return Response({"error": message}, status=400)

def generate_audio(request):
    text = request.GET.get('text', 'No text provided.')
    async def fetch_audio():
        communicate = edge_tts.Communicate(text, "en-US-AriaNeural")
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        return audio_data

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    audio_bytes = loop.run_until_complete(fetch_audio())
    return HttpResponse(audio_bytes, content_type="audio/mpeg")

# --- SOCIAL MEDIA CONFIG ENDPOINTS ---
@api_view(["GET"])
@permission_classes([AllowAny])
def get_social_links(request):
    config, _ = SocialMediaConfig.objects.get_or_create(id=1)
    return Response({
        "twitter": config.twitter,
        "youtube": config.youtube,
        "email": config.email,
        "insta": config.insta,
        "facebook": config.facebook,
        "linkedin": config.linkedin,
    })

@api_view(["GET", "POST"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def admin_social_links(request):
    config, _ = SocialMediaConfig.objects.get_or_create(id=1)
    if request.method == "POST":
        config.twitter = request.data.get("twitter", "")
        config.youtube = request.data.get("youtube", "")
        config.email = request.data.get("email", "")
        config.insta = request.data.get("insta", "")
        config.facebook = request.data.get("facebook", "")
        config.linkedin = request.data.get("linkedin", "") 
        config.save()
        return Response({"status": "success", "message": "Social links updated successfully"})
    return Response({
        "twitter": config.twitter,
        "youtube": config.youtube,
        "email": config.email,
        "insta": config.insta,
        "facebook": config.facebook,
        "linkedin": config.linkedin, 
    })
@api_view(["GET"])
@permission_classes([AllowAny])
def get_blogs(request):
    from .models import BlogPost
    from django.core.paginator import Paginator

    now = timezone.now()

    blogs = BlogPost.objects.filter(
        is_active=True
    ).filter(
        models.Q(publish_option="now") |
        models.Q(
            publish_option="schedule",
            scheduled_for__lte=now
        )
    ).order_by("-id")

    page_number = request.GET.get("page", "1")
    limit = request.GET.get("limit", "1")

    try:
        page_number = int(page_number)
    except (TypeError, ValueError):
        page_number = 1

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 1

    if page_number < 1:
        page_number = 1

    if limit < 1:
        limit = 1

    if limit > 20:
        limit = 20

    paginator = Paginator(blogs, limit)

    if page_number > paginator.num_pages and paginator.num_pages > 0:
        page_number = paginator.num_pages

    if paginator.num_pages == 0:
        return Response({
            "count": 0,
            "total_pages": 0,
            "current_page": 1,
            "next": None,
            "previous": None,
            "blogs": []
        })

    page_obj = paginator.get_page(page_number)

    data = []

    for b in page_obj.object_list:
        data.append({
            "id": b.id,
            "title": b.title,
            "description": b.description,
            "image_url": b.image_data or "",
            "publish_option": b.publish_option,
            "scheduled_for": (
                b.scheduled_for.strftime("%Y-%m-%d %H:%M")
                if b.scheduled_for
                else ""
            ),
            "created_at": b.created_at.strftime(
                "%Y-%m-%d %H:%M"
            )
        })

    return Response({
        "count": paginator.count,
        "total_pages": paginator.num_pages,
        "current_page": page_obj.number,
        "next": (
            page_obj.next_page_number()
            if page_obj.has_next()
            else None
        ),
        "previous": (
            page_obj.previous_page_number()
            if page_obj.has_previous()
            else None
        ),
        "blogs": data
    })


@api_view(["GET", "POST"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def admin_manage_blogs(request):
    from .models import BlogPost
    
    if request.method == "POST":
        title = request.data.get("title", "").strip()
        description = request.data.get("description", "").strip()
        publish_option = request.data.get("publish_option", "now")
        
        scheduled_for_str = request.data.get("scheduled_for")
        scheduled_for = parse_datetime(scheduled_for_str) if scheduled_for_str else None
        
        image_file = request.FILES.get("image")
        
        if not title or not description:
            return Response({"error": "Title and description are required."}, status=400)
            
        image_data_str = ""
        if image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            content_type = image_file.content_type or "image/jpeg"
            image_data_str = f"data:{content_type};base64,{encoded_string}"
            
        blog = BlogPost.objects.create(
            title=title,
            description=description,
            publish_option=publish_option,
            scheduled_for=scheduled_for if publish_option == "schedule" else None,
            image_data=image_data_str
        )
        return Response({
            "status": "success",
            "blog": {
                "id": blog.id,
                "title": blog.title,
                "description": blog.description,
                "image_url": blog.image_data,
                "publish_option": blog.publish_option,
                "scheduled_for": blog.scheduled_for.strftime("%Y-%m-%d %H:%M") if blog.scheduled_for else "",
                "created_at": blog.created_at.strftime("%Y-%m-%d %H:%M")
            }
        })
        
    blogs = BlogPost.objects.all().order_by("-id")
    data = [{
        "id": b.id,
        "title": b.title,
        "description": b.description,
        "image_url": b.image_data or "",
        "publish_option": b.publish_option,
        "scheduled_for": b.scheduled_for.strftime("%Y-%m-%d %H:%M") if b.scheduled_for else "",
        "created_at": b.created_at.strftime("%Y-%m-%d %H:%M"),
        "is_active": b.is_active
    } for b in blogs]
    return Response({"blogs": data})

@api_view(["PUT", "DELETE"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def admin_modify_blog(request, blog_id):
    from .models import BlogPost
    try:
        blog = BlogPost.objects.get(id=blog_id)
    except BlogPost.DoesNotExist:
        return Response({"error": "Blog not found."}, status=404)
        
    if request.method == "DELETE":
        blog.delete()
        return Response({"status": "success", "message": "Blog deleted successfully."})
        
    elif request.method == "PUT":
        title = request.data.get("title", "").strip()
        description = request.data.get("description", "").strip()
        publish_option = request.data.get("publish_option", "now")
        
        scheduled_for_str = request.data.get("scheduled_for")
        scheduled_for = parse_datetime(scheduled_for_str) if scheduled_for_str else None
        
        image_file = request.FILES.get("image")
        
        if not title or not description:
            return Response({"error": "Title and description are required."}, status=400)
            
        blog.title = title
        blog.description = description
        blog.publish_option = publish_option
        blog.scheduled_for = scheduled_for if publish_option == "schedule" else None
        
        if image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            content_type = image_file.content_type or "image/jpeg"
            blog.image_data = f"data:{content_type};base64,{encoded_string}"
            
        blog.save()
        return Response({
            "status": "success",
            "blog": {
                "id": blog.id,
                "title": blog.title,
                "description": blog.description,
                "image_url": blog.image_data,
                "publish_option": blog.publish_option,
                "scheduled_for": blog.scheduled_for.strftime("%Y-%m-%d %H:%M") if blog.scheduled_for else "",
                "created_at": blog.created_at.strftime("%Y-%m-%d %H:%M")
            }
        })

# --- BOOK ENDPOINTS ---
@api_view(["GET"])
@permission_classes([AllowAny])
def get_books(request):
    from .models import Book
    books = Book.objects.all().order_by("-id")
    data = [{
        "id": b.id,
        "title": b.title,
        "description": b.description,
        "url": b.url,
        "image_url": b.image_data or "",
    } for b in books]
    return Response({"books": data})

@api_view(["GET", "POST"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def admin_manage_books(request):
    from .models import Book
    
    if request.method == "POST":
        title = request.data.get("title", "").strip()
        description = request.data.get("description", "").strip()
        url = request.data.get("url", "").strip()
        image_file = request.FILES.get("image")

        if not title or not url:
            return Response({"error": "Title and URL are required."}, status=400)

        image_data_str = ""
        if image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            content_type = image_file.content_type or "image/jpeg"
            image_data_str = f"data:{content_type};base64,{encoded_string}"

        book = Book.objects.create(
            title=title,
            description=description,
            url=url,
            image_data=image_data_str
        )
        return Response({
            "status": "success",
            "book": {
                "id": book.id, "title": book.title, "description": book.description,
                "url": book.url, "image_url": book.image_data
            }
        })
    
    books = Book.objects.all().order_by("-id")
    data = [{"id": b.id, "title": b.title, "description": b.description, "url": b.url, "image_url": b.image_data} for b in books]
    return Response({"books": data})

@api_view(["PUT", "DELETE"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def admin_modify_book(request, book_id):
    from .models import Book
    try:
        book = Book.objects.get(id=book_id)
    except Book.DoesNotExist:
        return Response({"error": "Book not found."}, status=404)
    
    if request.method == "DELETE":
        book.delete()
        return Response({"status": "success", "message": "Book deleted successfully."})
    
    elif request.method == "PUT":
        title = request.data.get("title", "").strip()
        description = request.data.get("description", "").strip()
        url = request.data.get("url", "").strip()
        image_file = request.FILES.get("image")

        if not title or not url:
            return Response({"error": "Title and URL are required."}, status=400)
        
        book.title = title
        book.description = description
        book.url = url
        
        if image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            content_type = image_file.content_type or "image/jpeg"
            book.image_data = f"data:{content_type};base64,{encoded_string}"
        
        book.save()
        return Response({
            "status": "success",
            "book": {"id": book.id, "title": book.title, "description": book.description, "url": book.url, "image_url": book.image_data}
        })
    
@api_view(["GET"])
@permission_classes([AllowAny])
def get_active_rss_feeds(request):
    feeds = RSSFeed.objects.filter(is_active=True).order_by("name")
    data = [{"id": f.id, "name": f.name, "category": f.category, "url": f.url} for f in feeds]
    return Response({"feeds": data})

@api_view(["POST"])
@permission_classes([AllowAny])
def submit_volunteer(request):
    try:
        position_title = request.data.get("position", "")
        app = VolunteerApplication.objects.create(
            full_name=request.data.get("full_name", ""),
            email=request.data.get("email", ""),
            position=position_title,
            preferred_desk=request.data.get("preferred_desk", ""),
            pitch=request.data.get("pitch", ""),
            portfolio_url=request.data.get("portfolio_url", ""),
            resume_data=request.data.get("resume_data", ""),
            samples_data=request.data.get("samples_data", "")
        )
        
        # AUTO-DECREASE SEATS
        pos = OpenPosition.objects.filter(title=position_title).first()
        if pos and pos.seats > 0:
            pos.seats -= 1
            if pos.seats == 0:
                pos.is_active = False # Auto-hide if full
            pos.save()

        return Response({"status": "success", "id": app.id})
    except Exception as e:
        return Response({"error": str(e)}, status=400)


@api_view(["GET", "DELETE"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def admin_volunteers(request, app_id=None):
    if request.method == "DELETE" and app_id:
        try:
            app = VolunteerApplication.objects.get(id=app_id)
            
            # AUTO-RESTORE SEATS ON DELETE
            pos = OpenPosition.objects.filter(title=app.position).first()
            if pos:
                pos.seats += 1
                if pos.seats > 0:
                    pos.is_active = True # Auto-publish if seats open up
                pos.save()

            app.delete()
            return Response({"status": "success"})
        except VolunteerApplication.DoesNotExist:
            return Response({"error": "Not found"}, status=404)
            
    apps = VolunteerApplication.objects.all()
    data = [{
        "id": a.id, "full_name": a.full_name, "email": a.email, 
        "position": a.position, "preferred_desk": a.preferred_desk,
        "pitch": a.pitch, "portfolio_url": a.portfolio_url,
        "resume_data": a.resume_data, "samples_data": a.samples_data,
        "created_at": a.created_at.strftime("%Y-%m-%d %H:%M")
    } for a in apps]
    return Response({"applications": data})


@api_view(["GET", "POST", "PUT", "DELETE"])
@authentication_classes([CookieTokenAuthentication])
@permission_classes([IsAdminUser])
def admin_positions(request, pos_id=None):
    if request.method == "GET":
        positions = OpenPosition.objects.all()
        data = [{"id": p.id, "title": p.title, "seats": p.seats, "description": p.description, "is_active": p.is_active} for p in positions]
        return Response({"positions": data})
        
    elif request.method == "POST":
        pos = OpenPosition.objects.create(
            title=request.data.get("title", ""),
            seats=int(request.data.get("seats", 1)),
            description=request.data.get("description", "")
        )
        return Response({"status": "success", "id": pos.id})
        
    elif request.method == "PUT" and pos_id:
        try:
            pos = OpenPosition.objects.get(id=pos_id)
            
            # Allow updating active status, title, description, and seats
            if "is_active" in request.data: pos.is_active = request.data["is_active"]
            if "title" in request.data: pos.title = request.data["title"]
            if "description" in request.data: pos.description = request.data["description"]
            if "seats" in request.data: pos.seats = int(request.data["seats"])
                
            pos.save()
            return Response({"status": "success"})
        except OpenPosition.DoesNotExist:
            return Response({"error": "Not found"}, status=404)
            
    elif request.method == "DELETE" and pos_id:
        OpenPosition.objects.filter(id=pos_id).delete()
        return Response({"status": "success"})

@api_view(["GET"])
@permission_classes([AllowAny])
def get_positions(request):
    positions = OpenPosition.objects.filter(is_active=True)
    data = [{"id": p.id, "title": p.title, "seats": p.seats, "description": p.description} for p in positions]
    return Response({"positions": data})




@api_view(["POST"])
@throttle_classes([SensitiveActionThrottle])
def password_reset_request(request):
    email = request.data.get("email", "").strip()
    if not email:
        return Response({"error": "Email is required."}, status=400)
    
    associated_users = User.objects.filter(email=email)
    if associated_users.exists():
        config = SMTPConfig.objects.first()
        
        for user in associated_users:
            subject = "Password Reset Requested - Cyberbriefs"
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            
            reset_link = f"{FRONTEND_URL}/login?reset_uid={uid}&reset_token={token}"
            
            message = (
                f"Hello {user.username},\n\n"
                f"You requested a password reset for your Cyberbriefs account.\n"
                f"Click the link below to set a new password:\n{reset_link}\n\n"
                f"If you didn't request this, please ignore this email."
            )
            
            try:
                if config:
                    backend = EmailBackend(
                        host=config.host, 
                        port=config.port, 
                        username=config.username or config.email, 
                        password=config.password, 
                        use_tls=(config.security_protocol == 'TLS'), 
                        use_ssl=(config.security_protocol == 'SSL')
                    )
                    from_email = f"{config.name} <{config.email}>"
                    msg = EmailMultiAlternatives(subject, message, from_email, [user.email], connection=backend)
                    msg.send()
                else:
                    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
            except Exception:
                logger.exception("Failed to send password reset email via SMTP")
                
    return Response({"message": "If an account with that email exists, a password reset link has been sent."})


@api_view(["POST"])
@throttle_classes([SensitiveActionThrottle])
def password_reset_confirm(request):
    uid = request.data.get("uid")
    token = request.data.get("token")
    new_password = request.data.get("new_password")

    if not uid or not token or not new_password:
        return Response({"error": "All fields are required."}, status=400)

    try:
        user_id = force_str(urlsafe_base64_decode(uid))
        user = User.objects.get(pk=user_id)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        try:
            validate_password(new_password, user=user)
        except ValidationError as exc:
            return Response({"error": " ".join(exc.messages)}, status=400)
            
        user.set_password(new_password)
        user.save()
        return Response({"message": "Password has been successfully reset. You can now log in."})
    else:
        return Response({"error": "The reset link is invalid or has expired."}, status=400)
