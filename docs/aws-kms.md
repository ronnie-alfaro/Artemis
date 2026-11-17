# Cifrado de configuración con AWS KMS

Artemis conserva las configuraciones en PostgreSQL y cifra los secretos desde la aplicación. Con `ARTEMIS_KMS_KEY_ID` usa una clave simétrica de KMS para envolver una clave de datos AES-256 nueva por escritura. El contenido se cifra con AES-256-GCM. PostgreSQL recibe el contenido cifrado, el nonce y la clave de datos envuelta; no recibe claves en claro. El contexto KMS y los datos autenticados vinculan el contenido a cada integración.

Cubre las configuraciones guardadas desde el panel de Seerr, Karakeep, Usenet, WhatsApp y Telegram. No cifra el resto de tablas, los trabajos de agentes, las variables de entorno ni sustituye la autenticación existente. GitHub y los parámetros de arranque conservan su configuración de entorno.

## Coste y límites

AWS publica 20.000 solicitudes KMS gratuitas al mes, compartidas entre regiones. Una clave administrada por el cliente tiene un cargo base publicado de USD 1/mes, además de posibles cargos por rotación y solicitudes. Los créditos y la elegibilidad dependen de la cuenta. No se crea una clave ni se activa la rotación desde Artemis.

Esta integración usa una sola clave; no necesita Secrets Manager, CloudHSM ni claves multirregión. Cada escritura hace una llamada `GenerateDataKey`; cada lectura de un registro KMS hace una llamada `Decrypt`. Las pantallas que consultan configuraciones de habilidades también cuentan como lecturas. No se consulta KMS por cada mensaje ni por cada sondeo de Telegram. El comando de migración verifica cada escritura con una llamada adicional a `Decrypt`. No existe un límite de facturación automático dentro de Artemis: configura alertas de presupuesto y supervisa el consumo compartido de la cuenta.

Referencias: [precios](https://aws.amazon.com/kms/pricing/), [GenerateDataKey](https://docs.aws.amazon.com/kms/latest/APIReference/API_GenerateDataKey.html), [credenciales del SDK](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html).

## Clave y permisos

Usa una clave **simétrica, de cifrado/descifrado, de una sola región**, ya creada en tu cuenta. Se recomienda fijar su ARN en lugar de un alias para evitar que un cambio de alias deje inaccesibles los registros anteriores.

La identidad de Artemis necesita únicamente estas operaciones sobre esa clave:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["kms:GenerateDataKey", "kms:Decrypt"],
    "Resource": "arn:aws:kms:REGION:ACCOUNT_ID:key/KEY_ID",
    "Condition": {
      "StringEquals": {"kms:EncryptionContext:application": "artemis"}
    }
  }]
}
```

La política de la clave también debe permitir a esa identidad utilizarla. Artemis no necesita administrar, borrar ni crear claves. No uses el usuario root de AWS.

## Conexión del servidor

En `.env` solo hacen falta estos identificadores no secretos:

```dotenv
ARTEMIS_KMS_KEY_ID=arn:aws:kms:REGION:ACCOUNT_ID:key/KEY_ID
AWS_REGION=REGION
```

El SDK usa su cadena habitual de credenciales. En EC2 se recomienda un rol de instancia. Para un servidor externo se recomienda identidad temporal, por ejemplo IAM Roles Anywhere con un perfil `credential_process` y el helper instalado en la imagen; ese helper no viene incluido. Un inicio de sesión en la consola AWS no autentica automáticamente este servidor.

También se incluye `docker-compose.kms.yml` para montar un perfil SDK desde un directorio protegido del host:

```dotenv
ARTEMIS_AWS_CONFIG_DIR=/etc/artemis/aws
AWS_PROFILE=artemis
```

Ese directorio debe contener `config` y, si el perfil lo utiliza, `credentials`. Los archivos deben ser legibles por el UID 10001 del contenedor, con acceso restringido a ese usuario y al administrador del host. No los guardes en el repositorio ni dentro de las imágenes. Si utilizas credenciales estáticas como alternativa inicial, limita sus permisos a la política anterior y planifica su rotación. Las credenciales temporales en archivos estáticos caducan y no se renuevan solas.

Construcción y activación, una sola vez para incorporar esta versión y su configuración de arranque:

```sh
docker compose -f docker-compose.yml -f docker-compose.kms.yml up -d --build artemis-api artemis-web
```

Después usa siempre la misma combinación de archivos Compose para no retirar el montaje. Si utilizas rol de instancia y no el montaje de perfiles, basta el Compose principal. Los cambios posteriores de los canales desde el panel no requieren reiniciar Docker. Cambiar la región o la clave principal de arranque sí requiere una operación de mantenimiento; no cambies de ARN sin migrar los datos.

Para verificar permisos y conexión sin modificar datos (dos solicitudes KMS):

```sh
docker compose -f docker-compose.yml -f docker-compose.kms.yml exec -T artemis-api python -m app.infrastructure.kms_check
```

## Migración de lo existente

1. Conserva un respaldo de PostgreSQL y de la clave Fernet actual, por separado.
2. Mantén `ARTEMIS_CONFIG_ENCRYPTION_KEY` mientras existan registros Fernet. Al habilitar KMS, las lecturas antiguas siguen funcionando con ella, pero todas las escrituras nuevas usan KMS. Una falla de KMS nunca guarda contenido en claro ni usa Fernet como alternativa de escritura.
3. Con la nueva API arrancada, consulta los registros pendientes:

```sh
docker compose -f docker-compose.yml -f docker-compose.kms.yml exec -T artemis-api python -m app.infrastructure.migrate_config_kms
```

4. Para migrarlos y verificar cada sobre cifrado antes de confirmar una única transacción:

```sh
docker compose -f docker-compose.yml -f docker-compose.kms.yml exec -T artemis-api python -m app.infrastructure.migrate_config_kms --apply
```

El comando es idempotente y omite los registros KMS. No imprime credenciales. Conserva la clave Fernet en el respaldo para poder restaurar copias antiguas aunque la retires después del despliegue actual.

## Canales sin reinicios

En **Canales → Conexión de WhatsApp/Telegram** puedes modificar el token, los usuarios autorizados de Telegram, el nombre del agente de WhatsApp y la habilitación del canal. Un token vacío conserva el actual. Si la conexión todavía procede del entorno, **Guardar y aplicar** la copia a PostgreSQL cifrada; entonces puedes retirar las variables de token de `.env` en el próximo mantenimiento.

Telegram comprueba el token y la ausencia de webhook antes de guardarlo cuando está habilitado. No modifica ni borra webhooks automáticamente. WhatsApp valida el formato local y la conexión se refleja mediante el estado del sondeo; su token no se verifica remotamente antes de guardar.

Solo se reemplaza el sondeador del canal afectado; se mantienen las conversaciones, las habilidades y los trabajadores de resultados. Las modificaciones de configuración están serializadas por canal. Un cambio puede interrumpir un mensaje en curso; la bandeja persistente lo reintentará y existe la posibilidad de duplicar una respuesta si ya había sido enviada. Cambiar de bot o de nombre de agente crea una identidad distinta y sus asignaciones se configuran por separado.

Si KMS no está disponible, las operaciones de lectura/escritura que lo necesitan fallan; las conexiones ya cargadas pueden seguir trabajando en memoria. Un arranque que no consigue descifrar la configuración guardada falla de forma explícita. Esta versión supone una instancia de API por bot; no coordina recargas entre varias réplicas.

Authentik mantiene su función actual de autenticación. El acceso a estos endpoints debe pasar por la protección existente del panel; si se configura `ARTEMIS_ADMIN_TOKEN`, también se exige en la API. Los secretos no se devuelven en las respuestas, ni siquiera en errores de validación de los canales. No actives logs de depuración del SDK AWS en producción porque pueden incluir material sensible de las operaciones criptográficas.
