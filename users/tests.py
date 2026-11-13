from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .models import User
from .permissions import role_required


@override_settings(ALLOWED_HOSTS=['testserver'], LOGIN_URL='/users/login/')
class RolePolicyTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get('/privado/')
        self.view = role_required(User.Role.ORGANIZER, User.Role.ADMIN)(
            lambda request: HttpResponse('Permitido')
        )

    def test_public_account_defaults_to_client_without_technical_privileges(self):
        user = User()
        self.assertEqual(user.role, User.Role.CLIENT)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_role_field_rejects_unknown_roles(self):
        with self.assertRaises(ValidationError):
            User._meta.get_field('role').clean('visitor', User())

    def test_visitor_redirects_to_login(self):
        self.request.user = AnonymousUser()
        response = self.view(self.request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/users/login/?next=/privado/')

    def test_allowed_roles_can_access(self):
        for role in (User.Role.ORGANIZER, User.Role.ADMIN):
            with self.subTest(role=role):
                self.request.user = User(role=role)
                self.assertEqual(self.view(self.request).status_code, 200)

    def test_other_roles_are_denied(self):
        for role in (User.Role.CLIENT, User.Role.SCANNER):
            with self.subTest(role=role):
                self.request.user = User(role=role)
                with self.assertRaises(PermissionDenied):
                    self.view(self.request)

    def test_inactive_accounts_are_denied_even_for_admin(self):
        self.request.user = User(role=User.Role.ADMIN, is_active=False)
        with self.assertRaises(PermissionDenied):
            self.view(self.request)

    def test_technical_privileges_do_not_grant_business_role(self):
        self.request.user = User(role=User.Role.CLIENT, is_staff=True, is_superuser=True)
        with self.assertRaises(PermissionDenied):
            self.view(self.request)

    def test_role_is_not_a_hierarchy(self):
        self.assertFalse(User(role=User.Role.ADMIN).has_role(User.Role.ORGANIZER))

    def test_decorator_rejects_missing_or_misspelled_roles(self):
        for roles in ((), ('admn',)):
            with self.subTest(roles=roles):
                with self.assertRaises(ValueError):
                    role_required(*roles)


class AuthenticationFlowTests(TestCase):
    password = 'Prueba-Musica!4827'

    def setUp(self):
        self.user = User.objects.create_user(
            email='asistente@example.com', password=self.password
        )

    def registration_data(self, **extra):
        return {
            'first_name': 'Ana', 'last_name': 'Pérez',
            'date_of_birth': '2000-05-10', 'email': 'Nuevo@Example.com',
            'password1': self.password, 'password2': self.password, **extra,
        }

    def test_registration_hashes_password_and_ignores_privileged_fields(self):
        response = self.client.post(reverse('users:register'), self.registration_data(
            role='admin', is_staff=True, is_superuser=True, is_active=False,
        ))
        self.assertRedirects(response, reverse('users:login'))
        user = User.objects.get(email='nuevo@example.com')
        self.assertEqual(user.email, 'nuevo@example.com')
        self.assertEqual(user.role, User.Role.CLIENT)
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertTrue(user.is_active)
        self.assertTrue(user.password.startswith('argon2$'))
        self.assertTrue(user.check_password(self.password))

    def test_registration_rejects_duplicate_email_ignoring_case(self):
        response = self.client.post(reverse('users:register'), self.registration_data(
            email='ASISTENTE@example.com',
        ))
        self.assertEqual(response.status_code, 200)
        self.assertIn('email', response.context['form'].errors)
        self.assertEqual(User.objects.count(), 1)

    def test_registration_rejects_weak_mismatched_and_missing_values(self):
        for extra in (
            {'password1': '123', 'password2': '123'},
            {'password2': 'Distinta!4827'}, {'email': ''}, {'first_name': ''},
        ):
            with self.subTest(extra=extra):
                response = self.client.post(reverse('users:register'), self.registration_data(**extra))
                self.assertTrue(response.context['form'].errors)
                self.assertEqual(User.objects.count(), 1)

    def test_login_persists_session_and_logout_clears_it(self):
        response = self.client.post(reverse('users:login'), {
            'email': self.user.email, 'password': self.password,
        })
        self.assertRedirects(response, reverse('users:dashboard'))
        self.assertEqual(self.client.session['_auth_user_id'], str(self.user.pk))
        self.assertTrue(self.client.session.get_expire_at_browser_close())
        self.assertEqual(self.client.get(reverse('users:logout')).status_code, 405)
        self.assertRedirects(self.client.post(reverse('users:logout')), reverse('users:login'))
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.get(reverse('users:dashboard')).status_code, 302)

    def test_invalid_credentials_do_not_create_session(self):
        response = self.client.post(reverse('users:login'), {
            'email': self.user.email, 'password': 'incorrecta',
        })
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_email_login_ignores_case_and_surrounding_spaces(self):
        response = self.client.post(reverse('users:login'), {
            'email': '  ASISTENTE@EXAMPLE.COM  ', 'password': self.password,
        })
        self.assertRedirects(response, reverse('users:dashboard'))

    def test_username_cannot_be_used_instead_of_email(self):
        self.assertFalse(self.client.login(username='asistente', password=self.password))
        response = self.client.post(reverse('users:login'), {
            'email': 'asistente', 'password': self.password,
        })
        self.assertIn('email', response.context['form'].errors)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_unknown_email_has_generic_error(self):
        response = self.client.post(reverse('users:login'), {
            'email': 'desconocido@example.com', 'password': self.password,
        })
        self.assertContains(response, 'Correo electrónico o contraseña incorrectos.')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_ambiguous_existing_emails_are_denied(self):
        other = User.objects.create_user(email='otro@example.com', password=self.password)
        User.objects.filter(pk=other.pk).update(email='ASISTENTE@example.com')
        self.assertFalse(self.client.login(email=self.user.email, password=self.password))

    def test_private_panel_requires_login(self):
        self.assertRedirects(self.client.get(reverse('users:dashboard')),
                             reverse('users:login') + '?next=/panel/')

    def test_inactive_users_cannot_login(self):
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        response = self.client.post(reverse('users:login'), {
            'email': self.user.email, 'password': self.password,
        })
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_suspension_blocks_an_existing_session(self):
        self.client.login(email=self.user.email, password=self.password)
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        self.assertEqual(self.client.get(reverse('users:dashboard')).status_code, 302)

    def test_login_rejects_external_redirect(self):
        response = self.client.post(reverse('users:login'), {
            'email': self.user.email, 'password': self.password,
            'next': 'https://evil.example/',
        })
        self.assertRedirects(response, reverse('users:dashboard'))

    def test_authentication_forms_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        for name in ('register', 'login', 'logout'):
            with self.subTest(name=name):
                self.assertEqual(client.post(reverse('users:' + name), {}).status_code, 403)

    def test_templates_render_and_escape_personal_information(self):
        for name in ('register', 'login'):
            self.assertContains(self.client.get(reverse('users:' + name)), 'csrfmiddlewaretoken')
        self.user.first_name = '<script>alert(1)</script>'
        self.user.save(update_fields=['first_name'])
        self.client.login(email=self.user.email, password=self.password)
        response = self.client.get(reverse('users:dashboard'))
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
