FROM python:3.15-slim

RUN pip install --no-cache-dir asyncpg

COPY wol_service.py /wol_service.py

CMD ["python", "/wol_service.py"]
