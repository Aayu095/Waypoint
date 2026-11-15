# Waypoint app image — website + console + HTTP APIs (app/server.py).
#
# *** UNTESTED *** — Docker was unavailable on the machine Waypoint was
# built on, so this image has never been built or run. It is a thin
# packaging of the same stdlib-only Python app the tested scripted path
# (setup.sh + run.sh) serves. See docker-compose.yml's header.
FROM python:3.12-slim

WORKDIR /waypoint
COPY app/ app/
COPY data/ data/
COPY examples/ examples/
COPY site/ site/
COPY results/ results/

EXPOSE 8077
CMD ["python3", "app/server.py"]
