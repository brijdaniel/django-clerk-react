from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from app.models import User, Organisation, OrganisationMembership


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('clerk_id', 'email', 'first_name', 'last_name', 'is_active')
    search_fields = ('clerk_id', 'email', 'first_name', 'last_name')
    ordering = ('-date_joined',)
    fieldsets = (
        (None, {'fields': ('clerk_id', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('clerk_id',)}),
    )


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'clerk_org_id', 'created_at')
    search_fields = ('name', 'slug', 'clerk_org_id')


@admin.register(OrganisationMembership)
class OrganisationMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'organisation', 'role', 'created_at')
    list_filter = ('role',)
    search_fields = ('user__clerk_id', 'organisation__name')
