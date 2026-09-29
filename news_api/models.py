import re
from django.db import models
from django.contrib.auth.models import User

PROFESSOR_KEYWORD_MAP = {
    1: [
        "cancer research", "oncology research", "cancer study", "oncology study",
        "cancer biology", "tumor biology", "tumour biology", "cancer science",
        "oncology", "oncologist", "oncological", "tumor", "tumour",
        "cancer cell", "cancer cells", "tumor cell", "tumour cell",
        "cancer research institute", "oncology research", "basic cancer research",
        "translational oncology", "cancer discovery", "cancer mechanism",
        "carcinogenesis", "oncogenesis", "tumor microenvironment",
        "cancer stem cells", "metastasis research", "metastatic cancer research"
    ],

    2: [
        "breast cancer", "lung cancer", "prostate cancer", "colorectal cancer",
        "colon cancer", "rectal cancer", "pancreatic cancer", "liver cancer",
        "hepatocellular carcinoma", "stomach cancer", "gastric cancer",
        "ovarian cancer", "cervical cancer", "uterine cancer",
        "endometrial cancer", "kidney cancer", "renal cancer",
        "bladder cancer", "brain cancer", "brain tumor", "brain tumour",
        "glioblastoma", "leukemia", "leukaemia", "lymphoma",
        "hodgkin lymphoma", "non-hodgkin lymphoma", "multiple myeloma",
        "melanoma", "skin cancer", "thyroid cancer", "bone cancer",
        "sarcoma", "head and neck cancer", "oral cancer",
        "esophageal cancer", "oesophageal cancer", "testicular cancer",
        "pediatric cancer", "childhood cancer", "rare cancer",
        "blood cancer", "hematologic cancer", "hematological cancer"
    ],

    3: [
        "cancer diagnosis", "cancer detection", "early cancer detection",
        "cancer screening", "cancer screening test", "screening",
        "early detection", "diagnostic test", "cancer diagnosis test",
        "biopsy", "liquid biopsy", "blood test", "cancer blood test",
        "tumor marker", "tumour marker", "biomarker", "cancer biomarker",
        "imaging", "cancer imaging", "mri", "ct scan", "pet scan",
        "ultrasound", "mammogram", "mammography", "colonoscopy",
        "endoscopy", "pathology", "histopathology", "cytology",
        "genomic testing", "molecular diagnosis", "cancer diagnosis technology",
        "screening guidelines", "diagnostic imaging", "early diagnosis"
    ],

    4: [
        "cancer treatment", "cancer therapy", "oncology treatment",
        "chemotherapy", "radiotherapy", "radiation therapy",
        "radiation oncology", "immunotherapy", "cancer immunotherapy",
        "targeted therapy", "targeted cancer therapy", "hormone therapy",
        "hormonal therapy", "endocrine therapy", "surgery", "cancer surgery",
        "oncology surgery", "tumor surgery", "tumour surgery",
        "precision treatment", "cell therapy", "car-t", "car t-cell therapy",
        "stem cell transplant", "bone marrow transplant",
        "ablation", "cryotherapy", "photodynamic therapy",
        "combination therapy", "neoadjuvant therapy", "adjuvant therapy",
        "palliative care", "cancer pain management", "metastatic treatment"
    ],

    5: [
        "cancer drug", "cancer drugs", "oncology drug", "oncology drugs",
        "cancer medicine", "cancer medicines", "anticancer drug",
        "anti-cancer drug", "antineoplastic", "clinical trial",
        "clinical trials", "cancer clinical trial", "oncology clinical trial",
        "phase 1 trial", "phase 2 trial", "phase 3 trial", "phase 4 trial",
        "drug trial", "drug development", "drug approval",
        "cancer drug approval", "fda cancer", "fda oncology",
        "new cancer treatment", "new cancer drug", "experimental treatment",
        "experimental drug", "investigational drug", "trial results",
        "trial enrollment", "clinical research", "cancer vaccine",
        "therapeutic vaccine", "drug resistance", "treatment resistance"
    ],

    6: [
        "cancer genetics", "cancer genetic", "genetic cancer",
        "genetic testing", "genetic test", "genomic medicine",
        "genomics", "cancer genomics", "genome sequencing",
        "dna sequencing", "gene mutation", "gene mutations",
        "genetic mutation", "genetic mutations", "brca", "brca1",
        "brca2", "tp53", "egfr", "alk mutation", "kras",
        "braf", "her2", "her2-positive", "her2 negative",
        "biomarker", "molecular profiling", "molecular testing",
        "precision oncology", "precision medicine", "personalized medicine",
        "personalized cancer treatment", "hereditary cancer",
        "inherited cancer", "genetic counseling", "family cancer risk"
    ],

    7: [
        "cancer prevention", "cancer risk", "cancer risk reduction",
        "cancer prevention research", "cancer awareness", "cancer education",
        "healthy lifestyle", "cancer lifestyle", "smoking and cancer",
        "tobacco and cancer", "obesity and cancer", "diet and cancer",
        "nutrition and cancer", "exercise and cancer",
        "alcohol and cancer", "environmental cancer risk",
        "occupational cancer", "survivorship", "cancer survivor",
        "cancer survivors", "survivor care", "survivorship care",
        "quality of life", "cancer recovery", "living with cancer",
        "cancer recurrence", "recurrence prevention", "cancer rehabilitation",
        "mental health cancer", "supportive care", "end of life care"
    ],

    8: [
        "cancer organization", "cancer organizations", "cancer foundation",
        "cancer institute", "cancer center", "cancer centres",
        "national cancer institute", "nci", "american cancer society",
        "acs", "american association for cancer research", "aacr",
        "asco", "american society of clinical oncology",
        "world health organization cancer", "who cancer",
        "iarc", "cancer statistics", "cancer statistics report",
        "cancer incidence", "cancer mortality", "cancer death rate",
        "cancer prevalence", "cancer cases", "cancer burden",
        "global cancer burden", "cancer policy", "cancer policies",
        "cancer guidelines", "oncology guidelines", "cancer regulation",
        "cancer healthcare", "cancer funding", "cancer awareness month",
        "world cancer day", "public health cancer", "cancer epidemiology"
    ]
}


def determine_professor_by_content(text):
    if not text:
        return 1

    clean_text = text.lower()
    scores = {prof_id: 0 for prof_id in PROFESSOR_KEYWORD_MAP.keys()}

    for prof_id, keywords in PROFESSOR_KEYWORD_MAP.items():
        for kw in keywords:
            pattern = r'\b' + re.escape(kw) + r'\b'
            matches = len(re.findall(pattern, clean_text))

            if matches > 0:
                scores[prof_id] += matches

    best_prof = max(scores, key=scores.get)

    return best_prof if scores[best_prof] > 0 else 1


def get_random_professor():
    return 1


class Article(models.Model):
    guid = models.CharField(max_length=500, unique=True)
    source = models.CharField(max_length=150)
    category = models.CharField(max_length=50)
    title = models.TextField()
    ai_headline = models.TextField(blank=True)
    summary = models.TextField(blank=True)
    link = models.URLField(max_length=1000, blank=True)
    published = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    ai_status = models.CharField(max_length=20, default="pending")
    ai_locked_at = models.DateTimeField(null=True, blank=True)
    ai_completed_at = models.DateTimeField(null=True, blank=True)
    professor_id = models.IntegerField(default=get_random_professor)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        combined_text = f"{self.title} {self.ai_headline} {self.summary} {self.category}"
        self.professor_id = determine_professor_by_content(combined_text)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.ai_headline or self.title


class AdminTwoFactor(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="two_factor"
    )
    secret = models.CharField(max_length=64)
    is_enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"2FA - {self.user.username}"


class ArticleQuery(models.Model):
    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name="queries"
    )
    query_text = models.TextField()
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Query for {self.article.id}"


class SMTPConfig(models.Model):
    name = models.CharField(max_length=150, blank=True)
    email = models.CharField(max_length=150)
    reply_to = models.CharField(max_length=150, blank=True)
    host = models.CharField(max_length=200)
    port = models.IntegerField(default=587)
    username = models.CharField(max_length=200, blank=True)
    password = models.CharField(max_length=200)

    PROTOCOL_CHOICES = [
        ("TLS", "TLS"),
        ("SSL", "SSL"),
        ("NONE", "None"),
    ]

    security_protocol = models.CharField(
        max_length=10,
        choices=PROTOCOL_CHOICES,
        default="TLS"
    )
    daily_send_time = models.CharField(max_length=5, default="08:00")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"SMTP: {self.host}"


class Subscriber(models.Model):
    email = models.EmailField(unique=True)
    subscribed_at = models.DateTimeField(auto_now_add=True)
    emails_received = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-subscribed_at"]

    def __str__(self):
        return self.email


class Admin2FA(models.Model):
    user = models.OneToOneField(
        "auth.User",
        on_delete=models.CASCADE,
        related_name="admin_2fa"
    )
    totp_secret = models.CharField(max_length=64, blank=True)
    is_enabled = models.BooleanField(default=False)

    def __str__(self):
        return f"2FA for {self.user.username}"


class NewsletterSendLog(models.Model):
    send_date = models.DateField(unique=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.send_date)


class RSSFeed(models.Model):
    name = models.CharField(max_length=150)
    url = models.URLField(max_length=500, unique=True)
    category = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.category})"


class SocialMediaConfig(models.Model):
    twitter = models.URLField(max_length=500, blank=True)
    youtube = models.URLField(max_length=500, blank=True)
    email = models.CharField(max_length=500, blank=True)
    insta = models.URLField(max_length=500, blank=True)
    facebook = models.URLField(max_length=500, blank=True)
    linkedin = models.URLField(max_length=500, blank=True)

    def __str__(self):
        return "Social Media Links"


class BlogPost(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField()
    image_data = models.TextField(blank=True, null=True)
    publish_option = models.CharField(max_length=50, default="now")
    scheduled_for = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.title


class Book(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    url = models.URLField(max_length=500)
    image_data = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class VolunteerApplication(models.Model):
    full_name = models.CharField(max_length=255)
    email = models.EmailField()
    position = models.CharField(max_length=255)
    preferred_desk = models.CharField(max_length=255, blank=True)
    pitch = models.TextField()
    portfolio_url = models.URLField(max_length=500, blank=True)
    resume_data = models.TextField(blank=True, null=True)
    samples_data = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.full_name} - {self.position}"


class OpenPosition(models.Model):
    title = models.CharField(max_length=255)
    seats = models.IntegerField(default=1)
    description = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title