web: cd videocaller && daphne -b 0.0.0.0 -p $PORT videocaller.asgi:application
worker: cd videocaller && python manage.py qcluster
