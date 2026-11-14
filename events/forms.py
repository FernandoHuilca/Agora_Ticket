from decimal import Decimal
from django import forms
from django.utils import timezone
from .models import Event


class EventFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={
            'placeholder': 'Buscar por nombre o sala...',
            'class': 'form-input',
        }),
        label='Buscar'
    )
    category = forms.ChoiceField(
        required=False,
        choices=[('', 'Todas las categorías')] + list(Event.Category.choices),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Categoría'
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-input'}),
        label='Desde la fecha'
    )
    is_free = forms.ChoiceField(
        required=False,
        choices=[('', 'Todos'), ('1', 'Gratuitos'), ('0', 'De pago')],
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Modalidad'
    )


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = [
            'name', 'description', 'category', 'start_date', 'end_date',
            'location', 'capacity', 'is_free', 'price',
            'is_adult_only', 'max_tickets_per_user', 'image'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'required': True, 'minlength': 5, 'maxlength': 150,
                'placeholder': 'Ej. Concierto Sinfónico de Temporada'
            }),
            'description': forms.Textarea(attrs={
                'required': True, 'minlength': 20, 'maxlength': 2000, 'rows': 4
            }),
            'start_date': forms.DateTimeInput(
                attrs={'type': 'datetime-local', 'required': True},
                format='%Y-%m-%dT%H:%M'
            ),
            'end_date': forms.DateTimeInput(
                attrs={'type': 'datetime-local', 'required': True},
                format='%Y-%m-%dT%H:%M'
            ),
            'location': forms.TextInput(attrs={
                'required': True, 'maxlength': 200,
                'placeholder': 'Ej. Sala Principal - Casa de la Música'
            }),
            'capacity': forms.NumberInput(attrs={'required': True, 'min': 1, 'max': 5000}),
            'price': forms.NumberInput(attrs={'min': '0.00', 'step': '0.01'}),
            'max_tickets_per_user': forms.NumberInput(attrs={'min': 1, 'max': 10}),
            'image': forms.ClearableFileInput(attrs={
                'accept': '.jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ('start_date', 'end_date'):
            self.fields[field_name].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S']

    def clean_start_date(self):
        start_date = self.cleaned_data.get('start_date')
        # _state.adding es True cuando el evento es nuevo y aún no existe en la BD
        if self.instance._state.adding and start_date and start_date <= timezone.now():
            raise forms.ValidationError('La fecha de inicio del evento debe ser en el futuro.')
        return start_date

    def clean(self):
        cleaned_data = super().clean()
        is_free = cleaned_data.get('is_free')
        price = cleaned_data.get('price')
        new_capacity = cleaned_data.get('capacity')

        if is_free:
            cleaned_data['price'] = Decimal('0.00')
        elif price is None or price <= Decimal('0.00'):
            self.add_error('price', 'Para eventos de pago debes especificar un precio mayor a $0.00.')

        # Si el evento YA existe en la BD (edición), validar contra entradas ya vendidas
        if not self.instance._state.adding and new_capacity is not None:
            old_event = Event.objects.get(pk=self.instance.pk)
            tickets_sold = old_event.capacity - old_event.available_tickets
            if new_capacity < tickets_sold:
                self.add_error(
                    'capacity',
                    f'No puedes reducir la capacidad a {new_capacity} porque ya existen {tickets_sold} entradas emitidas.'
                )

        return cleaned_data

    def save(self, commit=True):
        # Si es edición de un evento existente en BD, recalcular available_tickets
        if not self.instance._state.adding:
            old_event = Event.objects.get(pk=self.instance.pk)
            tickets_sold = old_event.capacity - old_event.available_tickets
            self.instance.available_tickets = self.cleaned_data['capacity'] - tickets_sold
        else:
            self.instance.available_tickets = self.cleaned_data['capacity']
        return super().save(commit=commit)
