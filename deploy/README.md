# Deploy manifests

Place k8s YAMLs, Helm charts, or additional docker-compose overrides here.

## docker-compose.override.yml example

For local development overrides:

```yaml
version: "3.9"
services:
  api:
    build: .
    command: ["python", "-m", "nationcraft.cli", "api", "--reload"]
    volumes:
      - ./src:/app/src
      - ./game:/app/game
      - ./locales:/app/locales
      - ./plugins:/app/plugins
    environment:
      ENV: development
      LOG_FORMAT: console
```
