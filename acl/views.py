from django.shortcuts import render
from django.template import loader
from django.http import HttpResponse
from django.http import Http404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate
from django.conf import settings
from django.shortcuts import redirect
from django.views.generic import ListView, CreateView, UpdateView
from django.urls import reverse_lazy
from django import forms
from django.forms import ModelForm
from django.core.exceptions import ObjectDoesNotExist
from ipware import get_client_ip

from members.models import Tag,User
from members.forms import TagForm

from .models import Machine,Entitlement,PermitType

from storage.models import Storage
from memberbox.models import Memberbox

import logging
logger = logging.getLogger(__name__)

def matrix_mm(machine,member):
       out = { 'xs' : False, 'instructions_needed' : False, 'tags' : [] }
       out['mid'] = machine.id

       out['requires_instruction'] = machine.requires_instruction
       out['requires_permit'] = machine.requires_permit
       out['requires_form'] = machine.requires_form

       xs = True
       # Does the machine require a form; and does the user have that form on file.
       if machine.requires_form and not member.form_on_file:
          xs = False

       if machine.requires_permit: 
           ents = Entitlement.objects.filter(permit = machine.requires_permit, holder = member)
           if ents.count() < 1:
             return out

           for e in ents:
               out['has_permit'] = True
               if e.active == False:
                    xs = False

       for tag in Tag.objects.filter(owner = member):
          out['tags'].append(tag.tag)
       
       out['activated'] = xs
       out['xs'] = xs

       return out 

def matrix_m(machine):
    lst = {}
    for mbr in User.objects.filter(is_active = True).order_by():
       lst[ mbr ] = matrix_mm(machine,mbr)
  
    return lst 

@login_required
def api_index(request):
    lst = Machine.objects.order_by()
    perms = {}
    instructions= []
    ffa = []
    for m in lst:
       if m.requires_permit:
          if not m.requires_permit.name in perms:
              perms[ m.requires_permit.name ] = []
          perms[ m.requires_permit.name ].append(m)
       else:
         if m.requires_instruction:
            instructions.append(m)
         else:
            ffa.append(m)

    context = {
        'lst': lst,
        'perms': perms,
	'instructions': instructions,
	'freeforall': ffa,
    }
    return render(request, 'acl/index.html', context)

def api_index_legacy1(request, secret=None):
    if not (secret == settings.LV1_SECRET or (request.user and request.user.is_superuser)):
            return HttpResponse("XS denied",status=403,content_type="text/plain")

    out = ""
    for member in User.objects.filter(is_active = True):
        ok = False
        entitlements = Entitlement.objects.filter(holder = member).filter(active = True).filter(permit = settings.DOORS)
              
        if entitlements.count() <= 0:
                 continue

        tags = Tag.objects.filter(owner = member)
        for tag in tags:
            tagstr= '[{}]'.format(', '.join(tag.tag.split('-')))
            line = "{}:ok:{}".format(tagstr, member.name())
            if member.email:
                 line += ":{}".format(member.email)
            if member.phone_number:
                 line += " # {}".format(member.phone_number)
            out += line +"\n"

    return HttpResponse(out,content_type='text/plain')

def api_index_legacy2(request):
    ip, local = get_client_ip(request, proxy_trusted_ips=('127.0.0.1','::1'))
    if not (local or (request.user and request.user.is_superuser)):
            return HttpResponse("XS denied",status=403,content_type="text/plain")

    out = ""
    for member in User.objects.filter(is_active = True):

        machines = []
        for machine in Machine.objects.all().exclude(requires_permit = None).exclude(node_machine_name = None):

            if machine.requires_form and not member.form_on_file:
                  continue

            entitlements = Entitlement.objects.filter(holder = member).filter(active = True)

            if machine.requires_permit:
              entitlements = entitlements.filter(permit = machine.requires_permit)
              
            # shoudl we also check the other biz rules - such as permit by permit ?
            if entitlements.count() <= 0:
                 continue

            if machine.node_machine_name:
                 machines.append(machine.node_machine_name)
        if not machines:
            continue
 
        machines_string=  ','.join(machines).lower()

        tags = Tag.objects.filter(owner = member)
        for tag in tags:
               out += "{}:{}:{} # {}\n".format(tag.tag, machines_string, member.name(),tag.id)

    return HttpResponse(out,content_type='text/plain')

@login_required
def machine_overview(request, machine_id = None):
    instructors = []
    machines = Machine.objects.order_by('name')
    if machine_id:
        try:
            machines = machines.filter(pk = machine_id)
        except ObjectDoesNotExist as e:
            return HttpResponse("Machine not found",status=404,content_type="text/plain")
        machine = machines.first()
        permit = machine.requires_permit
        if permit:
            permit = PermitType.objects.get(pk = permit.id)
            if permit.permit:
                    instructors = Entitlement.objects.filter(permit=permit.permit)
            else:
                    instructors = Entitlement.objects.filter(permit=permit)
            instructors = instructors.order_by('holder__first_name'),
    lst = {}
    for mchn in machines:
       lst[ mchn.name ] = matrix_m(mchn)

    members =  User.objects.all().filter(is_active = True).order_by('first_name')

    context = {
       'members': members,
       'machines': machines,
       'lst': lst,
       'instructors': instructors
    }
    return render(request, 'acl/matrix.html', context)

@login_required
def members(request):
    members = User.objects.order_by('first_name')
    if not request.user.is_superuser:
        members = members.filter(is_active = True)

    context = {
       'title': "Members list",
       'members': members,
    }
    return render(request, 'acl/members.html', context)

@login_required
def member_overview(request,member_id = None):
    try:
       member = User.objects.get(pk=member_id)
    except ObjectDoesNotExist as e:
       return HttpResponse("User not found",status=404,content_type="text/plain")

    if not member.is_active and not request.user.is_superuser:
       return HttpResponse("User not found or access denied",status=404,content_type="text/plain")

    machines = Machine.objects.order_by()
    boxes = Memberbox.objects.all().filter(owner = member)
    storage = Storage.objects.all().filter(owner = member)
    normal_permits = {}
    for m in machines:
        normal_permits[ m.requires_permit ] = True

    specials = []
    for e in Entitlement.objects.all().filter(holder = member):
        if not e.permit in normal_permits:
            specials.append(e)

    lst = {}
    for mchn in machines:
       lst[ mchn.name ] = matrix_mm(mchn, member)
       lst[ mchn.name ][ 'path' ] = mchn.path()

    context = {
       'title': member.first_name + ' ' + member.last_name,
       'member': member,
       'machines': machines,
       'storage': storage,
       'boxes': boxes,
       'lst': lst,
       'permits': specials,
       'user' : request.user,
    }

    if member == request.user or request.user.is_superuser:
        tags = Tag.objects.filter(owner = member)
        context['tags'] = tags

    return render(request, 'acl/member_overview.html', context)

@login_required
def api_details(request,machine_id):
    try:
       machine = Machine.objects.get(pk=machine_id)
    except:
       raise Http404("Machine not found")

    context = {
       'machine': machine.name,
       'lst': matrix_m(machine)
       }
    return render(request, 'acl/details.txt', context, content_type='text/plain')

def missing(tof):
    holders = User.objects.all().filter(is_active = True).filter(form_on_file = tof).filter(isGivenTo__permit__has_permit__requires_form = True).distinct()
    return holders

@login_required
def missing_forms(request):
    context = {
	'title': 'Missing forms',
	'desc': 'Missing forms (of people who had instruction on a machine that needs it).',
	'amiss': missing(False)
    }
    return render(request, 'acl/missing.html',context)

@login_required
def filed_forms(request):
    # people_with_forms = User.objects.all().filter(form_on_file = True)
    context = {
	'title': 'Filed forms',
	'desc': 'Forms on file for people that also had instruction on something',
	'amiss': missing(True)
    }
    return render(request, 'acl/missing.html',context)

@login_required
def tag_edit(request,tag_id = None):
    try:
       tag = Tag.objects.get(pk=tag_id)
    except ObjectDoesNotExist as e:
       return HttpResponse("Tag not found",status=404,content_type="text/plain")

    context = {
        'title': 'Update a tag',
        'action': 'Update',
        'item': tag
        }
    if request.POST:
     form = TagForm(request.POST or None, request.FILES, instance = tag, canedittag = request.user.is_superuser)
     if form.is_valid() and request.POST:
        try:
            item = form.save(commit = False)
            item.changeReason = "Changed by {} via self service portal".format(request.user)
            item.save()
        except Exception as e:
            logger.error("Unexpected error during update of tag: {}".format(e))

        return redirect('overview', member_id=item.owner_id)

    form = TagForm(instance = tag, canedittag = request.user.is_superuser)
    context['form'] = form

    return render(request, 'acl/crud.html', context)

