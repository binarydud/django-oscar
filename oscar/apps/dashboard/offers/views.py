import datetime

from django.views.generic import (ListView, FormView, DeleteView, DetailView,
                                  CreateView, UpdateView)
from django.db.models.loading import get_model
from django.core.urlresolvers import reverse
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils.translation import ugettext_lazy as _

from oscar.core.loading import get_classes, get_class

ConditionalOffer = get_model('offer', 'ConditionalOffer')
Condition = get_model('offer', 'Condition')
Range = get_model('offer', 'Range')
Product = get_model('catalogue', 'Product')
OrderDiscount = get_model('order', 'OrderDiscount')
Benefit = get_model('offer', 'Benefit')
MetaDataForm, ConditionForm, BenefitForm, PreviewForm, OfferSearchForm = get_classes(
    'dashboard.offers.forms', [
        'MetaDataForm', 'ConditionForm', 'BenefitForm', 'PreviewForm',
        'OfferSearchForm'])
OrderDiscountCSVFormatter = get_class(
    'dashboard.offers.reports', 'OrderDiscountCSVFormatter')


class OfferListView(ListView):
    model = ConditionalOffer
    context_object_name = 'offers'
    template_name = 'dashboard/offers/offer_list.html'
    form_class = OfferSearchForm

    def get_queryset(self):
        qs = self.model._default_manager.filter(
            offer_type=ConditionalOffer.SITE)
        qs = self.sort_queryset(qs)

        self.description = _("All offers")

        # We track whether the queryset is filtered to determine whether we
        # show the search form 'reset' button.
        self.is_filtered = False
        self.form = self.form_class(self.request.GET)
        if not self.form.is_valid():
            return qs

        data = self.form.cleaned_data

        if data['name']:
            qs = qs.filter(name__icontains=data['name'])
            self.description = _("Offers matching '%s'") % data['name']
            self.is_filtered = True
        if data['is_active']:
            self.is_filtered = True
            today = datetime.date.today()
            qs = qs.filter(start_date__lte=today, end_date__gte=today)

        return qs

    def sort_queryset(self, queryset):
        sort = self.request.GET.get('sort', None)
        allowed_sorts = ['name', 'start_date', 'end_date', 'num_applications',
                         'total_discount']
        if sort in allowed_sorts:
            direction = self.request.GET.get('dir', 'desc')
            sort = ('-' if direction == 'desc' else '') + sort
            queryset = queryset.order_by(sort)
        return queryset

    def get_context_data(self, **kwargs):
        ctx = super(OfferListView, self).get_context_data(**kwargs)
        ctx['queryset_description'] = self.description
        ctx['form'] = self.form
        ctx['is_filtered'] = self.is_filtered
        return ctx


class OfferWizardStepView(FormView):
    wizard_name = 'offer_wizard'
    form_class = None
    step_name = None
    update = False
    url_name = None

    # Keep a reference to previous view class to allow checks to be made on
    # whether prior steps have been completed
    previous_view = None

    def get(self, request, *args, **kwargs):
        if self.update:
            self.offer = get_object_or_404(ConditionalOffer, id=kwargs['pk'])
        if not self.is_previous_step_complete(request):
            messages.warning(request, _("%s step not complete") % self.previous_view.step_name.title())
            return HttpResponseRedirect(self.get_back_url())
        return super(OfferWizardStepView, self).get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.update:
            self.offer = get_object_or_404(ConditionalOffer, id=kwargs['pk'])
        if not self.is_previous_step_complete(request):
            messages.warning(request, _("%s step not complete") %
                             self.previous_view.step_name.title())
            return HttpResponseRedirect(self.get_back_url())
        return super(OfferWizardStepView, self).post(request, *args, **kwargs)

    def is_previous_step_complete(self, request):
        if not self.previous_view:
            return True
        return self.previous_view.is_valid(self, request)

    def _key(self, step_name=None, is_object=False):
        key = step_name if step_name else self.step_name
        if self.update:
            key += str(self.offer.id)
        if is_object:
            key += '_obj'
        return key

    def _store_form_kwargs(self, form):
        session_data = self.request.session.setdefault(self.wizard_name, {})
        form_kwargs = {'data': form.cleaned_data.copy()}
        session_data[self._key()] = form_kwargs
        self.request.session.save()

    def _fetch_form_kwargs(self, step_name=None):
        if not step_name:
            step_name = self.step_name
        session_data = self.request.session.setdefault(self.wizard_name, {})
        return session_data.get(self._key(step_name), {})

    def _store_object(self, form):
        session_data = self.request.session.setdefault(self.wizard_name, {})
        session_data[self._key(is_object=True)] = form.save(commit=False)
        self.request.session.save()

    def _fetch_object(self, step_name):
        session_data = self.request.session.setdefault(self.wizard_name, {})
        return session_data.get(self._key(step_name, is_object=True), None)

    def _flush_session(self):
        self.request.session[self.wizard_name] = {}
        self.request.session.save()

    def get_form_kwargs(self, *args, **kwargs):
        form_kwargs = {}
        if self.update:
            form_kwargs['instance'] = self.get_instance()
        session_kwargs = self._fetch_form_kwargs()
        form_kwargs.update(session_kwargs)
        parent_kwargs = super(OfferWizardStepView, self).get_form_kwargs(
            *args, **kwargs)
        form_kwargs.update(parent_kwargs)
        return form_kwargs

    def get_context_data(self, **kwargs):
        ctx = super(OfferWizardStepView, self).get_context_data(**kwargs)
        if self.update:
            ctx['pk'] = self.kwargs.get('pk', None)
            ctx['offer'] = self.offer
        ctx['back_url'] = self.get_back_url()
        ctx['title'] = self.get_title()
        return ctx

    def get_back_url(self):
        if not self.previous_view:
            return None
        if self.update:
            return reverse(self.previous_view.url_name,
                           kwargs={'pk': self.kwargs['pk']})
        return reverse(self.previous_view.url_name)

    def get_title(self):
        if self.update:
            return _("Edit %(step_name)s") % {
                'step_name': self.step_name}
        return _('Create new offer: %s') % self.step_name

    def form_valid(self, form):
        self._store_form_kwargs(form)
        self._store_object(form)
        return super(OfferWizardStepView, self).form_valid(form)

    def get_success_url(self):
        if self.update:
            return reverse(self.success_url_name,
                           kwargs={'pk': self.kwargs['pk']})
        return reverse(self.success_url_name)

    @classmethod
    def is_valid(cls, current_view, request):
        if current_view.update:
            return True
        return current_view._fetch_object(cls.step_name) is not None


class OfferMetaDataView(OfferWizardStepView):
    step_name = 'metadata'
    form_class = MetaDataForm
    template_name = 'dashboard/offers/metadata_form.html'
    url_name = 'dashboard:offer-metadata'
    success_url_name = 'dashboard:offer-condition'

    def get_instance(self):
        return self.offer


class OfferConditionView(OfferWizardStepView):
    step_name = 'condition'
    form_class = ConditionForm
    template_name = 'dashboard/offers/condition_form.html'
    url_name = 'dashboard:offer-condition'
    success_url_name = 'dashboard:offer-benefit'
    previous_view = OfferMetaDataView

    def get_instance(self):
        return self.offer.condition


class OfferBenefitView(OfferWizardStepView):
    step_name = 'benefit'
    form_class = BenefitForm
    template_name = 'dashboard/offers/benefit_form.html'
    url_name = 'dashboard:offer-benefit'
    success_url_name = 'dashboard:offer-preview'
    previous_view = OfferConditionView

    def get_instance(self):
        return self.offer.benefit


class OfferPreviewView(OfferWizardStepView):
    step_name = 'preview'
    form_class = PreviewForm
    template_name = 'dashboard/offers/preview.html'
    previous_view = OfferBenefitView
    url_name = 'dashboard:offer-preview'

    def get_context_data(self, **kwargs):
        ctx = super(OfferPreviewView, self).get_context_data(**kwargs)
        ctx['offer'] = self._fetch_object('metadata') or self.offer
        ctx['condition'] = self._fetch_object('condition') or self.offer.condition
        ctx['benefit'] = self._fetch_object('benefit') or self.offer.benefit
        return ctx

    def get_form_kwargs(self, *args, **kwargs):
        return super(OfferWizardStepView, self).get_form_kwargs(*args, **kwargs)

    def form_valid(self, form):
        condition = self._fetch_object('condition') or self.offer.condition
        condition.save()
        benefit = self._fetch_object('benefit') or self.offer.benefit
        benefit.save()

        offer = self._fetch_object('metadata') or self.offer
        offer.condition = condition
        offer.benefit = benefit
        offer.save()

        self._flush_session()

        if self.update:
            msg = _("Offer '%s' updated") % offer.name
        else:
            msg = _("Offer '%s' created!") % offer.name
        messages.success(self.request, msg)

        return HttpResponseRedirect(self.get_success_url())

    def get_title(self):
        return _('Preview')

    def get_success_url(self):
        return reverse('dashboard:offer-list')


class OfferDeleteView(DeleteView):
    model = ConditionalOffer
    template_name = 'dashboard/offers/offer_delete.html'
    context_object_name = 'offer'

    def get_success_url(self):
        messages.success(self.request, _("Offer deleted!"))
        return reverse('dashboard:offer-list')


class OfferDetailView(ListView):
    # Slightly odd, but we treat the offer detail view as a list view so the
    # order discounts can be browsed.
    model = OrderDiscount
    template_name = 'dashboard/offers/offer_detail.html'
    context_object_name = 'order_discounts'

    def dispatch(self, request, *args, **kwargs):
        self.offer = get_object_or_404(ConditionalOffer, pk=kwargs['pk'])
        return super(OfferDetailView, self).dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if 'suspend' in request.POST:
            return self.suspend()
        elif 'unsuspend' in request.POST:
            return self.unsuspend()

    def suspend(self):
        if self.offer.is_suspended:
            messages.error(self.request, _("Offer is already suspended"))
        else:
            self.offer.suspend()
            messages.success(self.request, _("Offer suspended"))
        return HttpResponseRedirect(
            reverse('dashboard:offer-detail', kwargs={'pk': self.offer.pk}))

    def unsuspend(self):
        if not self.offer.is_suspended:
            messages.error(
                self.request,
                _("Offer cannot be reinstated as it is not currently "
                  "suspended"))
        else:
            self.offer.unsuspend()
            messages.success(self.request, _("Offer reinstated"))
        return HttpResponseRedirect(
            reverse('dashboard:offer-detail', kwargs={'pk': self.offer.pk}))

    def get_queryset(self):
        return self.model.objects.filter(offer_id=self.offer.pk)

    def get_context_data(self, **kwargs):
        ctx = super(OfferDetailView, self).get_context_data(**kwargs)
        ctx['offer'] = self.offer
        return ctx

    def render_to_response(self, context):
        if self.request.GET.get('format') == 'csv':
            formatter = OrderDiscountCSVFormatter()
            return formatter.generate_response(context['order_discounts'],
                                               offer=self.offer)
        return super(OfferDetailView, self).render_to_response(context)


class RangeListView(ListView):
    model = Range
    context_object_name = 'ranges'
    template_name = 'dashboard/offers/range_list.html'


class RangeCreateView(CreateView):
    model = Range
    template_name = 'dashboard/offers/range_form.html'

    def get_success_url(self):
        messages.success(self.request, _("Range created"))
        return reverse('dashboard:range-list')


class RangeUpdateView(UpdateView):
    model = Range
    template_name = 'dashboard/offers/range_form.html'

    def get_success_url(self):
        messages.success(self.request, _("Range updated"))
        return reverse('dashboard:range-list')


class RangeDeleteView(DeleteView):
    model = Range
    template_name = 'dashboard/offers/range_delete.html'
    context_object_name = 'range'

    def get_success_url(self):
        messages.warning(self.request, _("Range deleted"))
        return reverse('dashboard:range-list')


class RangeProductListView(ListView):
    model = Product
    template_name = 'dashboard/offers/range_product_list.html'
    context_object_name = 'products'

    def get(self, request, *args, **kwargs):
        self.range = get_object_or_404(Range, id=self.kwargs['pk'])
        return super(RangeProductListView, self).get(request, *args, **kwargs)

    def get_queryset(self):
        return self.range.included_products.all()

    def get_context_data(self, **kwargs):
        ctx = super(RangeProductListView, self).get_context_data(**kwargs)
        ctx['range'] = self.range
        return ctx