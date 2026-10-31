FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[pdf,mcp]" \
 && useradd --create-home --uid 10001 app
USER app
ENV ACABC_AUDIT_LOG=/tmp/acabc_audit.jsonl
EXPOSE 8000
# Reference build: roles come from a header. Put a real identity provider in front before any non-demo use (docs/SECURITY.md).
CMD ["uvicorn", "acabc.api:app", "--host", "0.0.0.0", "--port", "8000"]
