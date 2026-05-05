ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG TORCH_PACKAGE=torch==2.11.0+cpu

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential curl \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir \
  -i https://pypi.tuna.tsinghua.edu.cn/simple \
  --extra-index-url https://mirrors.aliyun.com/pytorch-wheels/cpu \
  -r requirements.txt
RUN pip install --no-cache-dir \
  --index-url ${TORCH_INDEX_URL} \
  ${TORCH_PACKAGE}

COPY app ./app
COPY evaluate_retrieval.py ./evaluate_retrieval.py
COPY evaluation_cases.json ./evaluation_cases.json
COPY experiments ./experiments

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
