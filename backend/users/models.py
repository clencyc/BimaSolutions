from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_NAME_CHOICES = [
        ('underwriter', 'Underwriter'),
        ('secondary_stakeholder', 'Secondary Stakeholder'),
    ]

    role_name = models.CharField(
        max_length=50,
        choices=ROLE_NAME_CHOICES,
        default='secondary_stakeholder',
    )
    name = models.CharField(max_length=255, blank=True, default='')

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role_name = 'underwriter'
        elif self.is_staff:
            self.role_name = 'secondary_stakeholder'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.username} ({self.role_name})"