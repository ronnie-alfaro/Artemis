# WhatsApp Third-Party Agent tracking

Artemis reserves a `WhatsApp3PAdapter` interface only. The detailed public technical protocol is not sufficiently documented; Artemis does not reverse engineer it, probe endpoints, or invent headers, SDKs, WebSockets, or payloads.

Before implementation, official documentation must define: API-key authentication and rotation, connection endpoint, inbound and outbound message mechanisms, media, message/conversation identifiers, rate limits, reconnect behavior, errors, and webhook verification if applicable. The core interacts only with `ChannelAdapter`, so this work must not modify the agent runtime.
