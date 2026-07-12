PY := backend/.venv/bin/python
PIP := backend/.venv/bin/pip

.PHONY: db install seed backend frontend sidecar

db:
	createdb agentic_crm || true

install:
	python3 -m venv backend/.venv
	$(PIP) install -r backend/requirements.txt
	cd frontend && npm install
	cd sidecar && npm install

seed:
	$(PY) backend/manage.py migrate
	$(PY) backend/manage.py seed

backend:
	$(PY) backend/manage.py runserver

frontend:
	cd frontend && npm run dev

sidecar:
	node sidecar/index.js
