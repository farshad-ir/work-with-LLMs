# Python AI Gateway

### A unified gateway for accessing and managing hundreds of AI models

## About the Project

In an era where artificial intelligence models are evolving rapidly and companies are competing to deliver increasingly powerful solutions, accessing a wide range of models and managing connections to multiple providers has become an important challenge.

Companies such as OpenRouter, NVIDIA, TokenRouter, Agnes, and SambaNova each offer collections of AI models. The number of available models continues to grow, making their selection, testing, and management increasingly complex.

This project was created to simplify that process.

**Python AI Gateway** is a unified access gateway that provides connectivity to hundreds of AI models through multiple providers.

The system currently has access to more than 500 models. However, this is not a fixed limit. Any number of valid API keys from supported providers can be added to the Gateway, allowing the available model catalog to grow as new providers and credentials are introduced.

## General Architecture

The Gateway runs on a computer or server, and users connect to it through an API.

Instead of requiring each user to communicate directly with multiple AI services, the Gateway manages these connections and provides users with a single, unified access point.

The current deployment has one connected user, but the project architecture is designed to support future expansion and additional users.

## Key Features

- Connectivity to multiple AI service providers
- Unified access to hundreds of models through a single Gateway
- Support for adding new providers without a fixed limit on their number
- API key management through environment variables
- Automatic retrieval and rebuilding of provider model lists
- A centralized model catalog
- Recording of model test results and usage statistics
- Infrastructure for model selection and rotation

## Log Files

The system uses three main log files to record events and monitor its operation:

| File | Purpose |
|---|---|
| `logs/gateway.log` | Records Gateway events and activity |
| `logs/uvicorn.log` | Records Uvicorn server runtime logs |
| `data/rotation.log` | Records model selection and rotation events |

These files help monitor system status, investigate errors, and analyze Gateway behavior.

## Configurable Parameters

The model rotation component defines three main numeric parameters that can be adjusted according to system requirements:

| Parameter | Default Value | Purpose |
|---|---:|---|
| `DEFAULT_TEST_INPUT_CHAR_LIMIT` | `1,750,000` | Default maximum number of input characters used for model testing |
| `CONFIRMED_MODEL_ENTRY_CHARS` | `1,000` | Number of characters allocated per confirmed model entry |
| `CONFIRMED_MODEL_CHAR_LIMIT` | `1,750,000` | Maximum character limit for confirmed models |

These parameters are defined in `app/model_rotation.py` and can be modified to adjust model testing and rotation behavior.

## Management Scripts

The project includes several scripts for managing providers, rebuilding the model catalog, and checking model status.

| Script | Purpose |
|---|---|
| `scripts/rebuild_provider_catalog.py` | Retrieves provider model lists and rebuilds the centralized catalog |
| `scripts/set_provider_status.py` | Changes the status of a provider's models to `untested`, `failed`, or `confirmed` |
| `scripts/list_confirmed_models.py` | Lists confirmed models and displays their related statistics |

### Model Status

Models can have different statuses during the testing and management process:

- `untested`: The model has not yet been tested.
- `failed`: The model did not pass testing.
- `confirmed`: The model successfully passed a previous test.

The management scripts make it possible to review and update these statuses and inspect model performance statistics.

## Project Goal

The goal is to build a flexible and extensible infrastructure that provides unified access across a large and continuously growing number of AI models and providers.

With this architecture, adding a new company or provider does not require redesigning the entire system. A new provider can be introduced to the Gateway, its connection can be tested, and its models can be added to the centralized catalog.

This project is designed for the continuously evolving AI landscape, where the number of models, companies, and service providers is constantly changing.
