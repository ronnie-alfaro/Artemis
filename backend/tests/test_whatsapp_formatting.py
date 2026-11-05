from app.application.whatsapp_formatting import format_whatsapp, whatsapp_chunks


def test_markdown_adapts_to_whatsapp_and_is_idempotent():
    original = (
        "## Resultado\n\n**Terminado**\n• Servicio activo\n"
        "1) Revisar\nEscribe ‘estado’.\n~~Pendiente~~\n"
        "[Documentación](https://example.com/help)"
    )
    result = format_whatsapp(original)
    assert "*Resultado*" in result
    assert "*Terminado*" in result
    assert "- Servicio activo" in result
    assert "1. Revisar" in result
    assert "`estado`" in result
    assert "~Pendiente~" in result
    assert "Documentación\nhttps://example.com/help" in result
    assert format_whatsapp(result) == result


def test_code_and_urls_keep_literal_characters():
    original = (
        '```python\n# comment\nprint("**literal**")\n```\n`a__b`\nhttps://example.com/a__b?q=~~x~~'
    )
    result = format_whatsapp(original)
    assert '```\n# comment\nprint("**literal**")\n```' in result
    assert "`a__b`" in result
    assert "https://example.com/a__b?q=~~x~~" in result


def test_long_message_preserves_all_text_and_prefers_paragraphs():
    text = "\n\n".join(f"Párrafo {i}: " + "palabra " * 70 for i in range(20))
    chunks = whatsapp_chunks(text)
    assert len(chunks) > 1
    assert all(len(chunk) <= 3900 for chunk in chunks)
    assert "".join(chunks) == text.strip()
    assert all(chunk.endswith(" ") or chunk.endswith("\n") for chunk in chunks[:-1])


def test_code_fences_are_balanced_across_messages():
    text = "```python\n" + 'print("hola")\n' * 800 + "```"
    chunks = whatsapp_chunks(text)
    assert len(chunks) > 1
    assert all(len(chunk) <= 3900 for chunk in chunks)
    assert all(chunk.count("```") % 2 == 0 for chunk in chunks)
    assert sum(chunk.count('print("hola")') for chunk in chunks) == 800
