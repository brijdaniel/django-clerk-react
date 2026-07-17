"""
factory-boy factories for creating test data.

Provides factories for the framework models with realistic fake data using
Faker. Factories automatically handle ForeignKey relationships via SubFactory.

Usage:
    # Create with defaults
    user = UserFactory()

    # Override specific fields
    user = UserFactory(first_name='Alice')

    # Create batch
    users = UserFactory.create_batch(10)

    # Build without saving to database
    user = UserFactory.build()
"""

import factory
from django.utils.text import slugify
from factory.django import DjangoModelFactory

from app.models import Config, Organisation, OrganisationMembership, User


class UserFactory(DjangoModelFactory):
    """Factory for User model."""

    class Meta:
        model = User

    clerk_id = factory.Sequence(lambda n: f'user_{n:05d}')
    email = factory.Faker('email')
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')


class OrganisationFactory(DjangoModelFactory):
    """Factory for Organisation model."""

    class Meta:
        model = Organisation

    clerk_org_id = factory.Sequence(lambda n: f'org_{n:05d}')
    name = factory.Faker('company')
    slug = factory.LazyAttribute(lambda obj: slugify(obj.name))
    is_active = True


class OrganisationMembershipFactory(DjangoModelFactory):
    """Factory for OrganisationMembership model."""

    class Meta:
        model = OrganisationMembership

    user = factory.SubFactory(UserFactory)
    organisation = factory.SubFactory(OrganisationFactory)
    role = 'member'
    is_active = True


class ConfigFactory(DjangoModelFactory):
    """Factory for Config model (generic per-org key/value settings)."""

    class Meta:
        model = Config

    organisation = factory.SubFactory(OrganisationFactory)
    name = factory.Sequence(lambda n: f'config_key_{n}')
    value = factory.Faker('word')


# ============================================================================
# Convenience Factory Functions
# ============================================================================

def create_org_with_user(org_name='Test Org', user_email='test@example.com', role='member'):
    """
    Create an organisation with a user membership.

    Returns:
        tuple: (organisation, user, membership)
    """
    org = OrganisationFactory(name=org_name)
    user = UserFactory(email=user_email)
    membership = OrganisationMembershipFactory(
        organisation=org,
        user=user,
        role=role
    )
    return org, user, membership
