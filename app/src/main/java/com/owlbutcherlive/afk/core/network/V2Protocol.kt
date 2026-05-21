package com.owlbutcherlive.afk.core.network

import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.annotations.SerializedName

/**
 * V2 WebSocket protocol — native thread event streaming over /ws/v2/thread.
 *
 * Protocol:
 *   Client → Server: JSON with type, request_id, and command-specific fields
 *   Server → Client: JSON with type, request_id, and event-specific fields
 *
 * All commands carry a request_id for correlation.
 */
object V2Protocol {

    private val gson = Gson()

    // ─── Client commands (outgoing) ─────────────────────────────────────

    /** Create a "hello" command — initialize session and get protocol info. */
    fun hello(requestId: String = ""): String {
        return gson.toJson(mapOf(
            "type" to "hello",
            "request_id" to requestId,
        ))
    }

    /** Create a "subscribe" command. */
    fun subscribe(threadId: String, requestId: String = ""): String {
        return gson.toJson(mapOf(
            "type" to "subscribe",
            "thread_id" to threadId,
            "request_id" to requestId,
        ))
    }

    /** Create an "unsubscribe" command. */
    fun unsubscribe(threadId: String, requestId: String = ""): String {
        return gson.toJson(mapOf(
            "type" to "unsubscribe",
            "thread_id" to threadId,
            "request_id" to requestId,
        ))
    }

    /** Create a "start_turn" command — send user message to a thread. */
    fun startTurn(threadId: String, text: String, requestId: String = ""): String {
        return gson.toJson(mapOf(
            "type" to "start_turn",
            "thread_id" to threadId,
            "text" to text,
            "request_id" to requestId,
        ))
    }

    /** Create an "interrupt_turn" command. */
    fun interruptTurn(turnId: String, requestId: String = ""): String {
        return gson.toJson(mapOf(
            "type" to "interrupt_turn",
            "turn_id" to turnId,
            "request_id" to requestId,
        ))
    }

    /** Create a "request_snapshot" command. */
    fun requestSnapshot(threadId: String, requestId: String = ""): String {
        return gson.toJson(mapOf(
            "type" to "request_snapshot",
            "thread_id" to threadId,
            "request_id" to requestId,
        ))
    }

    /** Create a "heartbeat" command. */
    fun heartbeat(requestId: String = ""): String {
        return gson.toJson(mapOf(
            "type" to "heartbeat",
            "request_id" to requestId,
        ))
    }

    // ─── Server events (incoming parsing) ───────────────────────────────

    /**
     * Parsed V2 WebSocket event from the server.
     * Events carry V2-native concepts: thread_id, turn_id, items.
     */
    sealed class V2Event {
        data class HelloResponse(
            val requestId: String,
            val protocolVersion: String,
            val serverSessionId: String,
            val runtimes: List<Map<String, String>>,
            val endpoints: Map<String, String>,
        ) : V2Event()

        data class ThreadSnapshot(
            val requestId: String,
            val threadId: String,
            val title: String,
            val status: String,
            val runtimeKind: String,
            val turnCount: Int,
            val activeTurnId: String,
            val activeTurnStatus: String,
            val items: List<V2Item>,
            val lastMessagePreview: String,
            val createdAt: String,
            val updatedAt: String,
        ) : V2Event()

        data class ItemAppended(
            val requestId: String?,
            val threadId: String,
            val turnId: String,
            val item: V2Item,
        ) : V2Event()

        data class TurnStarted(
            val requestId: String,
            val threadId: String,
            val turnId: String,
        ) : V2Event()

        data class TurnCompleted(
            val requestId: String,
            val threadId: String,
            val turnId: String,
            val replyText: String,
            val durationMs: Int = 0,
        ) : V2Event()

        data class TurnFailed(
            val requestId: String,
            val threadId: String,
            val turnId: String,
            val error: String,
        ) : V2Event()

        data class Ack(
            val requestId: String,
            val status: String,
            val threadId: String? = null,
        ) : V2Event()

        data class Error(
            val requestId: String,
            val code: String,
            val message: String,
        ) : V2Event()

        data class Pong(
            val requestId: String,
        ) : V2Event()

        /** Unknown/unhandled event type. */
        data class Unknown(val rawType: String, val rawJson: String) : V2Event()
    }

    /** A thread item in V2 — the atomic unit of thread content. */
    data class V2Item(
        val id: String,
        val turnId: String,
        val turnIndex: Int,
        val kind: String,
        val index: Int,
        val role: String,
        val content: String,
        val createdAt: String,
        val metadata: Map<String, Any> = emptyMap(),
    )

    /**
     * Parse a raw WebSocket message into a V2Event.
     *
     * @param raw The raw JSON string from the server.
     * @return Parsed V2Event, or null if parsing fails.
     */
    fun parse(raw: String): V2Event? {
        return try {
            val json = gson.fromJson(raw, JsonObject::class.java)
            val type = json.get("type")?.asString ?: return null
            val requestId = json.get("request_id")?.asString ?: ""
            val threadId = json.get("thread_id")?.asString ?: ""

            when (type) {
                "hello_response" -> V2Event.HelloResponse(
                    requestId = requestId,
                    protocolVersion = json.get("protocol_version")?.asString ?: "",
                    serverSessionId = json.get("server_session_id")?.asString ?: "",
                    runtimes = parseRuntimeList(json.getAsJsonArray("runtimes")),
                    endpoints = parseStringMap(json.getAsJsonObject("endpoints")),
                )

                "thread_snapshot" -> V2Event.ThreadSnapshot(
                    requestId = requestId,
                    threadId = json.get("thread_id")?.asString ?: threadId,
                    title = json.get("title")?.asString ?: "",
                    status = json.get("status")?.asString ?: "",
                    runtimeKind = json.get("runtime_kind")?.asString ?: "",
                    turnCount = json.get("turn_count")?.asInt ?: 0,
                    activeTurnId = json.get("active_turn_id")?.asString ?: "",
                    activeTurnStatus = json.get("active_turn_status")?.asString ?: "",
                    items = parseItems(json.getAsJsonArray("items")),
                    lastMessagePreview = json.get("last_message_preview")?.asString ?: "",
                    createdAt = json.get("created_at")?.asString ?: "",
                    updatedAt = json.get("updated_at")?.asString ?: "",
                )

                "item_appended" -> V2Event.ItemAppended(
                    requestId = requestId.ifEmpty { null },
                    threadId = threadId,
                    turnId = json.get("turn_id")?.asString ?: "",
                    item = parseItem(json.getAsJsonObject("item")) ?: V2Item(
                        id = "", turnId = "", turnIndex = 0, kind = "", index = 0,
                        role = "", content = "", createdAt = "",
                    ),
                )

                "turn_started" -> V2Event.TurnStarted(
                    requestId = requestId,
                    threadId = threadId,
                    turnId = json.get("turn_id")?.asString ?: "",
                )

                "turn_completed" -> V2Event.TurnCompleted(
                    requestId = requestId,
                    threadId = threadId,
                    turnId = json.get("turn_id")?.asString ?: "",
                    replyText = json.get("reply_text")?.asString ?: "",
                    durationMs = json.get("duration_ms")?.asInt ?: 0,
                )

                "turn_failed" -> V2Event.TurnFailed(
                    requestId = requestId,
                    threadId = threadId,
                    turnId = json.get("turn_id")?.asString ?: "",
                    error = json.get("error")?.asString ?: "Unknown error",
                )

                "ack" -> V2Event.Ack(
                    requestId = requestId,
                    status = json.get("status")?.asString ?: "ok",
                    threadId = json.get("thread_id")?.asString,
                )

                "error" -> V2Event.Error(
                    requestId = requestId,
                    code = json.get("code")?.asString ?: "error",
                    message = json.get("message")?.asString ?: "",
                )

                "pong" -> V2Event.Pong(requestId = requestId)

                else -> V2Event.Unknown(rawType = type, rawJson = raw)
            }
        } catch (e: Exception) {
            null
        }
    }

    private fun parseItems(array: com.google.gson.JsonArray?): List<V2Item> {
        if (array == null) return emptyList()
        return array.mapNotNull { element ->
            parseItem(element?.asJsonObject)
        }
    }

    private fun parseItem(obj: com.google.gson.JsonObject?): V2Item? {
        if (obj == null) return null
        return V2Item(
            id = obj.get("id")?.asString ?: "",
            turnId = obj.get("turn_id")?.asString ?: "",
            turnIndex = obj.get("turn_index")?.asInt ?: 0,
            kind = obj.get("kind")?.asString ?: "",
            index = obj.get("index")?.asInt ?: 0,
            role = obj.get("role")?.asString ?: "",
            content = obj.get("content")?.asString ?: "",
            createdAt = obj.get("created_at")?.asString ?: "",
            metadata = parseMetadata(obj.getAsJsonObject("metadata")),
        )
    }

    private fun parseMetadata(obj: com.google.gson.JsonObject?): Map<String, Any> {
        if (obj == null) return emptyMap()
        val result = mutableMapOf<String, Any>()
        obj.entrySet().forEach { (key, value) ->
            result[key] = when {
                value.isJsonPrimitive -> value.asString
                else -> value.toString()
            }
        }
        return result
    }

    private fun parseRuntimeList(array: com.google.gson.JsonArray?): List<Map<String, String>> {
        if (array == null) return emptyList()
        return array.mapNotNull { element ->
            val obj = element?.asJsonObject ?: return@mapNotNull null
            mapOf(
                "kind" to (obj.get("kind")?.asString ?: ""),
                "status" to (obj.get("status")?.asString ?: ""),
            )
        }
    }

    private fun parseStringMap(obj: com.google.gson.JsonObject?): Map<String, String> {
        if (obj == null) return emptyMap()
        val result = mutableMapOf<String, String>()
        obj.entrySet().forEach { (key, value) ->
            result[key] = value?.asString ?: ""
        }
        return result
    }
}
