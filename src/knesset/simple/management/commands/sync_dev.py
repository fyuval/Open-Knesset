# no handling now: posts

from django.core.management.base import NoArgsCommand
from django.core.management import call_command
from django.db.models import get_apps, get_models, get_model
from django.db import transaction

class Command(NoArgsCommand):
    """Export the sqlite database for developers, while whitelisting user data"""

    reset_models = ('contenttypes.contenttype', )
    ignore_models = ('sessions.session', 'auth.message', 'mailer',
        'accounts.email_validation', 'hitcount', 'actstream.follow',
        'avatar')
    only_latest = ('actstream.action', )

    LATEST_COUNT = 1000
    DB = 'dev'
    COMMIT_EVERY = 100

    def handle_noargs(self, **options):

        call_command('syncdb', database=self.DB, interactive=False,
                migrate_all=True)

        # reset data in needed models
        for reset_model in self.reset_models:
            model = get_model(*reset_model.split('.'))
            model.objects.using(self.DB).delete()

        ignore_models = []
        ignore_apps = []

        self.verbosity = int(options.get('verbosity', 1))

        for label in self.ignore_models:
            to_ignore = label.split('.')

            if len(to_ignore) == 1:
                ignore_apps.append(label)
            else:
                ignore_models.append(to_ignore)

        only_latest = [x.split('.') for x in self.only_latest]

        app_list = get_apps()
        untracked_m2m = []

        all_models = get_models()

        for app in app_list:
            for model in get_models(app):
                app_label = model._meta.app_label
                module_name = model._meta.module_name

                name_pair = [app_label, module_name]

                if not (app_label in ignore_apps or name_pair in ignore_models):

                    # m2m fields without through table won't be tracked here, so we
                    # need to collect it and handle it later
                    for field in model._meta.many_to_many:
                        try:
                            through_model = getattr(model, field.name).through
                            if through_model not in all_models:
                                untracked_m2m.append(through_model)
                        # ReverseGenericRelatedObjectsDescriptor have no
                        # through attribute, ignore
                        except AttributeError,e :
                            pass
                    self.sync_model(model, name_pair in only_latest)

        for model in set(untracked_m2m):
            self.sync_model(model)

    def sync_model(self, model, only_latest=False):
        """Save model instances to the dev db"""

        app_label = model._meta.app_label
        module_name = model._meta.module_name

        name_pair = [app_label, module_name]

        if self.verbosity > 1:
            print "Exporting %s.%s" % tuple(name_pair)

        qs = model.objects.all()

        # do we need only latest ?
        if only_latest:
            qs = qs[:self.LATEST_COUNT]
            if self.verbosity > 1:
                print "    Exporting only %d latest" % self.LATEST_COUNT

        counted = 0
        total = 0
        for obj in qs.iterator():
            if counted > self.COMMIT_EVERY:
                if self.verbosity > 1:
                    print "    committed %d so far" % total
                transaction.commit(using=self.DB)
                counted = 0

            # obfuscate user data
            if name_pair == ['auth', 'user']:
                obj.set_unusable_password()
                uid = 'user_%s' % obj.pk
                obj.username = uid
                obj.first_name = uid
                obj.last_name = uid
                obj.email = '%s@example.com' % uid

            if name_pair == ['user', 'userprofile']:
                obj.description = u''

            obj.save(using=self.DB)
            counted += 1
            total += 1
        print "    %d Exported" % total
