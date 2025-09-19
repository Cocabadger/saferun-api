# SafeRun API

Open-source safety middleware for AI agents - prevent destructive actions before they happen.

## Features

- 🛡️ **Safety Middleware**: Intercepts potentially dangerous AI agent actions
- 🔄 **Dry-run Previews**: Test actions without executing them
- 📊 **Risk Scoring**: Intelligent risk assessment for all operations
- ✅ **Approval Workflows**: Human-in-the-loop for high-risk actions
- ↩️ **Rollback Capabilities**: Undo actions when things go wrong
- 🔌 **Provider Integrations**: Support for GitHub, Notion, and more
- 🔐 **API Key Authentication**: Secure access control

## Quick Start

1. Clone the repository:
```bash
git clone https://github.com/Cocabadger/saferun-api.git
cd saferun-api
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

4. Start the server:
```bash
python -m saferun.main
```

## API Endpoints

- `POST /api/v1/actions/preview` - Preview an action without executing
- `POST /api/v1/actions/execute` - Execute an action with safety checks
- `POST /api/v1/actions/rollback` - Rollback a previous action
- `GET /api/v1/actions/{action_id}/status` - Get action status
- `POST /api/v1/auth/token` - Authenticate and get access token

## Supported Providers

- **GitHub**: Repository operations, PR management, issue handling
- **Notion**: Page creation, database updates, content management

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

MIT License - see LICENSE file for details.
