from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from app.models import (
    User, Organisation, OrganisationMembership,
    Contact, ContactGroup, ContactGroupMember,
    Template, Schedule, Config, CreditTransaction,
)


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


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'email', 'phone', 'organisation', 'is_active', 'opt_out')
    search_fields = ('first_name', 'last_name', 'email', 'phone', 'company')
    list_filter = ('is_active', 'opt_out', 'organisation')


@admin.register(ContactGroup)
class ContactGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'organisation', 'is_active', 'created_at')
    search_fields = ('name',)
    list_filter = ('is_active', 'organisation')


@admin.register(ContactGroupMember)
class ContactGroupMemberAdmin(admin.ModelAdmin):
    list_display = ('contact', 'group', 'joined_at')
    search_fields = ('contact__first_name', 'contact__last_name', 'group__name')


@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'version', 'organisation', 'is_active', 'created_at')
    search_fields = ('name',)
    list_filter = ('is_active', 'organisation')


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ('pk', 'name', 'phone', 'status', 'format', 'scheduled_time', 'sent_time', 'organisation')
    search_fields = ('name', 'phone', 'contact__first_name', 'contact__last_name')
    list_filter = ('status', 'format', 'organisation')


@admin.register(Config)
class ConfigAdmin(admin.ModelAdmin):
    list_display = ('name', 'value', 'organisation')
    search_fields = ('name',)
    list_filter = ('organisation',)


@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    list_display = ('organisation', 'transaction_type', 'amount', 'unit_rate', 'balance_after', 'description', 'format', 'created_at')
    list_filter = ('transaction_type', 'format', 'organisation')
    search_fields = ('description', 'organisation__name')
