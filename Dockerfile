ARG COATBENCH_DEPS_IMAGE=python:3.11-slim
FROM ${COATBENCH_DEPS_IMAGE} AS dependencies
USER root
WORKDIR /build/coatbench
COPY requirements.txt .
RUN python -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: -r requirements.txt && python -m pip check

FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOST=0.0.0.0 PORT=8000 COATBENCH_DATA=/var/lib/coatbench
WORKDIR /opt/coatbench
COPY --from=dependencies /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY coatbench ./coatbench
COPY static ./static
RUN useradd -U -u 11519 coatbench && install -d -o coatbench -g coatbench /var/lib/coatbench
USER coatbench
EXPOSE 8000
CMD ["python", "-m", "coatbench"]
