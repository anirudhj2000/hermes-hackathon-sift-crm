PY := backend/.venv/bin/python
PIP := backend/.venv/bin/pip

.PHONY: db install seed backend frontend sidecar stop

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
	@if lsof -nP -tiTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then \
		echo "ERROR: port 8000 is already in use by:"; \
		lsof -nP -iTCP:8000 -sTCP:LISTEN; \
		echo "Run 'make stop' to kill leftover dev servers, then retry."; \
		exit 1; \
	fi
	$(PY) backend/manage.py runserver

# Kill leftover dev servers on 8000 (Django), 5173 (Vite), 3001 (sidecar).
stop:
	@for port in 8000 5173 3001; do \
		pids=$$(lsof -nP -tiTCP:$$port -sTCP:LISTEN 2>/dev/null || true); \
		if [ -n "$$pids" ]; then \
			echo "Killing listeners on :$$port (pids: $$pids)"; \
			kill $$pids 2>/dev/null || true; \
		else \
			echo "Port $$port is free."; \
		fi; \
	done

frontend:
	cd frontend && npm run dev

sidecar:
	node sidecar/index.js
