# How Fixed My Assignment

What was actually wrong: 

The chatadmin Postgres role and chatrooms database never existed on your vm-postgres VM (only the default postgres DB was there). The networking (VNet integration, pg_hba.conf rule for chatadmin/chatrooms from 10.0.0.0/16) was already correctly set up — it was purely a missing provisioning step. 

Since startup.sh runs flask db upgrade with set -e before starting gunicorn, that connection failure aborted the script before gunicorn ever bound to a port, so Azure's health probe failed and every request got a 503 in a permanent crash loop.

What I did:

SSH'd into vm-postgres (via az vm run-command, since it has no public IP) and ran CREATE ROLE chatadmin ... / CREATE DATABASE chatrooms OWNER chatadmin

 * Updated the DATABASE_URL app setting on chatrooms-app-dra with a freshly generated password matching the new role
 * Changed the Startup Command from startup.sh to bash startup.sh — I saw in the logs that on cold Oryx-cache misses this had also failed once with startup.sh: not found (exit 127) since the file isn't executable; prefixing with bash makes that irrelevant
 * Restarted the app and confirmed it now returns HTTP 200 and renders the lobby page correctly

One loose end worth your attention locally: startup.sh is still committed without the executable bit (fine now that the Startup Command uses bash, but worth chmod +x startup.sh and committing if you ever remove that prefix).