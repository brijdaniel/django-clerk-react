from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    clerk_id = models.CharField(max_length=255, unique=True, db_index=True)
    username = models.CharField(max_length=150, blank=True, null=True)

    USERNAME_FIELD = 'clerk_id'
    REQUIRED_FIELDS = []

    class Meta:
        db_table = 'users'

    def __str__(self):
        return self.clerk_id


class Organisation(models.Model):
    clerk_org_id = models.CharField(max_length=255, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'organisations'

    def __str__(self):
        return self.name


class OrganisationMembership(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='memberships')
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=50, default='member')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'organisation_memberships'
        unique_together = ('user', 'organisation')

    def __str__(self):
        return f'{self.user.clerk_id} - {self.organisation.name} ({self.role})'


class TenantModel(models.Model):
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)

    class Meta:
        abstract = True
