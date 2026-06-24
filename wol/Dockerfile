FROM python:3.12-slim

RUN pip install --no-cache-dir asyncpg

COPY wol_service.py /wol_service.py

CMD ["python", "/wol_service.py"]
