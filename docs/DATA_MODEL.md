# ark local staging archive — content types & metadata

Append-only archive under `out/`. Re-runs **upsert** by stable IDs; files are not deleted unless you delete them locally.

Integrity rule: `integrity.status` is `ok` only when claimed data was verified. `partial` means something is incomplete or unverified; `failed` / `skipped` are category-level outcomes (printed to the console; also written to `export/run_report.json` when `--diagnostic` is set).

---

## Layout overview

| Content | Path |
|---|---|
| Durable upsert DB (source of truth) | `out/archive/archive.sqlite` |
| Messages media | `out/messages/{thread}/` |
| Voicemail / voice memo audio | `out/blobs/voicemail/`, `out/blobs/voicememos/` |
| Scratch / decrypted DBs | `out/work/` (cleaned after run unless `--keep-work`) |
| Optional JSON dumps | `out/export/` — only with `--diagnostic` |

Message attachments are named `{lowercase-guid}{ext}` inside the thread folder (no nested `files/` directory).

---

## 1. Messages (`imessage` / SMS / RCS)

**Source:** encrypted iTunes/Apple Devices backup → `HomeDomain` `Library/SMS/sms.db` + `MediaDomain` `Library/SMS/Attachments/` and `Library/SMS/StickerCache/`.

**Stable ID:** message `guid` (Apple). Attachments use attachment `guid` (lowercased).

**One JSONL line = one message.** Useful fields:

### Identity & thread
| Field | Meaning |
|---|---|
| `id` | Message GUID (upsert key) |
| `thread` | Folder / thread key (`{chat_id}_{chat_identifier}`) |
| `chat_id` | Numeric chat ROWID |
| `chat_identifier` | Handle or group id (e.g. `+1503…`, `chat…`) |
| `chat_display_name` | Group/contact display name when set |
| `source` | Always `imessage` (extractor name; not the transport) |
| `backup_id` | Backup UDID folder name |
| `extracted_at` | When this record was written |

### People & body
| Field | Meaning |
|---|---|
| `from` | Sender (handle or your number / `me`) |
| `to` | List of recipients / participants |
| `text` | Plain text (from `text` column or decoded `attributedBody`) |
| `text_source` | `text` or `attributedBody` |
| `subject` | Subject line when present |

### Blue vs green (and friends)
| Field | Meaning |
|---|---|
| `service` | Raw Apple value: `iMessage`, `SMS`, `RCS`, `satelliteSMS`, `iMessageLite`, … |
| `bubble` | Viewer hint: `blue` (iMessage / iMessageLite) or `green` (SMS / MMS / RCS / satelliteSMS) |

### Delivery / read status (`status`)
| Field | Meaning |
|---|---|
| `is_from_me` | You sent it |
| `is_sent` / `is_delivered` / `is_read` / `is_finished` | Delivery flags |
| `date_delivered` / `date_read` / `date_played` | ISO timestamps |
| `date_edited` / `date_retracted` | Edit / unsend when present |
| `error` | Non-zero send error code |
| `was_downgraded` | iMessage fell back toward SMS-like delivery |
| `was_delivered_quietly` | Quiet delivery |
| `did_notify_recipient` | Notify flag when present |

### Flags (`flags`)
Booleans when set: `is_audio_message`, `is_played`, `is_system_message`, `is_emote`, `is_spam`, `is_empty`, `is_stewie`, `is_sos`, `is_critical`, `is_time_sensitive`.

### Reactions & replies
| Field | Meaning |
|---|---|
| `reaction` | Tapback: `type`, `name` (`love`/`like`/…), `target_guid`, `emoji` |
| `reply.reply_to_guid` | Direct reply target |
| `reply.thread_originator_guid` | Thread root |
| `reply.thread_originator_part` | Part index in threaded UI |

### Effects & rich payloads
| Field | Meaning |
|---|---|
| `effect` | `expressive_send_style_id` (slam / loud / invisible ink / …) |
| `balloon_bundle_id` | App balloon / rich link bundle |
| `item_type` / `group_title` / `group_action_type` | System/group events |
| `schedule_type` / `schedule_state` | Scheduled send |
| `part_count` | Multipart message parts |
| `account` / `account_guid` / `country` | Account context |

### Attachments (`attachments[]`)
| Field | Meaning |
|---|---|
| `id` | Attachment GUID (lowercase) |
| `filename` | Local file name in thread folder (`{guid}.ext`) |
| `original_filename` | Name from the phone when known |
| `mime_type` / `uti` | Type info |
| `kind` | `file` or `sticker` |
| `byte_size_db` / `byte_size_disk` | Expected vs on-disk size |
| `sha256` | Set only when `verified` |
| `verified` | File present and size matches DB (when DB size known) |
| `is_outgoing` | Sent by you |
| `transfer_state` | Apple transfer state code |
| `created_date` | Attachment created |
| `original_guid` | When Apple links a derivative |

### Integrity (`integrity`)
| Field | Meaning |
|---|---|
| `status` | `ok` or `partial` |
| `notes` | Human-readable issues (missing media, size mismatch, undecoded body, stubs) |
| `has_attributed_body` | Rich body blob existed |

**Media domains extracted:** `Library/SMS/Attachments/%` and `Library/SMS/StickerCache/%` (MediaDomain). Zero-byte `pluginPayloadAttachment` stubs are noted but not treated as real media.

---

## 2. Voicemail

**Store:** `archive.sqlite` `voicemails` table (+ optional `--diagnostic` → `export/voicemail.json`)  
**Audio:** `out/blobs/voicemail/.../{row_id}.amr` (+ `.transcript` when present)  
**Stable ID:** `voicemail:{row_id}` (ROWID maps 1:1 to `{row_id}.amr`)

| Field | Meaning |
|---|---|
| `id` | `voicemail:{ROWID}` |
| `row_id` | DB ROWID (= audio basename) |
| `account_uuid` | Account/label UUID from DB (not unique per message) |
| `date` | When left (ISO) |
| `from` | Sender number |
| `callback_number` | Callback |
| `to` | Receiver when present |
| `duration_sec` | Length in seconds |
| `expiration` / `trashed_date` | When meaningful (garbage sentinels stripped) |
| `token` / `flags` / `label` | Carrier/app metadata |
| `audio.path` | Relative path under `blobs/` |
| `audio.sha256` / `audio.byte_size` / `audio.format` | `amr` when verified |
| `audio.verified` | Non-empty file present |
| `transcript` | Text transcript when `.transcript` file exists |
| `integrity` | `ok` / `partial` / `failed` + notes |

---

## 3. Voice memos

**Store:** `archive.sqlite` `voicememos` table (+ optional `--diagnostic` → `export/voicememos.json`)  
**Audio:** `out/blobs/voicememos/Recordings/*.m4a`  
**Stable ID:** `voicememo:{filename}`  
**Source domain:** `AppDomainGroup-group.com.apple.VoiceMemos.shared`

| Field | Meaning |
|---|---|
| `id` | `voicememo:{filename}` |
| `title` | Best-effort title (DB / composition / filename) |
| `date` | Recording time when known |
| `filename` | Original `.m4a` name |
| `audio.path` / `sha256` / `byte_size` / `format` | `m4a` |
| `audio.verified` | Non-empty file |
| `integrity` | Status + notes |

---

## 4. Contacts

**Store:** `archive.sqlite` `contacts` table (+ optional `--diagnostic` → `export/contacts.json`)  
**Stable ID:** `contact:{person_rowid}`

| Field | Meaning |
|---|---|
| `id` | `contact:{ROWID}` |
| `display_name` | Computed display string |
| `name.first` / `middle` / `last` / `nickname` | Name parts |
| `organization` | Company |
| `note` | Notes field |
| `phones[]` | `{ label, value, property }` |
| `emails[]` | same shape |
| `urls[]` | same shape |
| `extended_multivalues[]` | Other ABMultiValue rows (social, etc.) |
| `extended_fields` | Other ABPerson columns worth keeping |
| `integrity` | Usually `ok` |

---

## 5. Wi‑Fi known networks

**Store:** `archive.sqlite` `wifi_networks` table (+ optional `--diagnostic` → `export/wifi.json`)  
**Primary source:** `SystemPreferencesDomain` / `com.apple.wifi.known-networks.plist`  
**Stable ID:** `wifi:{ssid}:{bssid_or_index}`

| Field | Meaning |
|---|---|
| `id` | Upsert key |
| `ssid` | Network name |
| `bssid` | AP MAC when present |
| `security` | e.g. WPA2 Personal |
| `hidden` | Hidden SSID flag |
| `last_joined` / `last_auto_joined` | When known |
| `source_plist` | Which plist yielded the row |
| `extended` | Extra keys (joined-by-user timestamps, home state, etc.; binaries summarized) |
| `integrity` | Status + notes |

---

## 6. WhatsApp

**When available:** plaintext `ChatStorage.sqlite` in the backup.  
**On this device’s backup:** only `ChatStorage.sqlite.enc` (WhatsApp’s own crypto) → category **skipped**.

When extractable, records include roughly: `id`, `date`, `from`, `to`, `is_from_me`, `text`, `attachments`, `integrity` (and note if media was absent from the backup).

---

## 7. Archive SQLite (`out/archive/archive.sqlite`)

Tables used for headless upsert (same logical records as JSON exports):

- `messages` — key `id` (message guid)
- `attachments` — key `id` (attachment guid)
- `voicemails` — key `id`
- `voicememos` — key `id`
- `contacts` — key `id`
- `wifi_networks` — key `id`
- `whatsapp_messages` — key `id`
- `meta` — run metadata

Payload JSON for each row is stored in `payload_json` for round-tripping into the server UI or another DB.

---

## Commands

```sh
ark --backup /path/to/MobileSync/Backup/<udid> --out ./staging messages
ark --backup … voicemail|voicememos|contacts|wifi|whatsapp|all
```

Password: `ARK_BACKUP_PASSWORD` or `agent.yml`, else prompt.
