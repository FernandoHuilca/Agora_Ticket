from django import forms
from django.forms import formset_factory


class AttendeeForm(forms.Form):
    attendee_name = forms.CharField(
        label='Nombre',
        max_length=150,
        required=True,
    )
    attendee_email = forms.EmailField(
        label='Correo (opcional)',
        required=False,
    )


def attendee_formset_factory(max_num):
    return formset_factory(
        AttendeeForm,
        extra=0,
        min_num=1,
        max_num=max_num,
        validate_min=True,
        validate_max=True,
    )
