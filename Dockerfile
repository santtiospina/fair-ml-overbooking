FROM mcr.microsoft.com/devcontainers/python:3.10-bullseye 

USER root

# Instalar UV para la gestión de paquetes python
COPY --from=ghcr.io/astral-sh/uv:0.11.0 /uv /usr/local/bin

# Configurar las variables de entorno
ENV TZ=America/Bogota

USER vscode
WORKDIR /workspaces
