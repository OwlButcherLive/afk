package com.owlbutcherlive.afk.core.network

import android.util.Log
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.annotations.SerializedName
import com.owlbutcherlive.afk.domain.AgentOnlineStatus
import com.owlbutcherlive.afk.domain.ChatEvent
import com.owlbutcherlive.afk.domain.MessageRole

/**
 * Typed protocol layer for the Agent Gateway WebSocket chat endpoint.
 *
 * Parses incoming raw JSON strings into sealed [ChatEvent] types
 * and serializes outgoing messages into the expected JSON shape.
 */
object ChatProtocol {

    private const val TAG = "ChatProtocol"
    private val gson = Gson()

    /**
     * Parse an incoming WebSocket JSON string into a typed [ChatEvent].
     * Returns null if the payload cannot be parsed.
     */
    fun parse(raw: String): ChatEvent? {
        return try {
            val json = gson.fromJson(raw, JsonObject::class.java)
            val type = json.get("type")?.asString ?: return null

            @Suppress("UNCHECKED_CAST")
            when (type) {
                "message" -> {
                    val msg = gson.fromJson(raw, IncomingMessagePayload::class.java)
                    ChatEvent.Message(
                        id = msg.id,
                        agentId = msg.agentId,
                        role = MessageRole.fromApi(msg.role),
                        text = msg.text,
                        timestamp = msg.timestamp
                    )
                }

                "typing" -> {
                    val typing = gson.fromJson(raw, TypingPayload::class.java)
                    ChatEvent.Typing(
                        agentId = typing.agentId,
                        isTyping = typing.isTyping
                    )
                }

                "error" -> {
                    val err = gson.fromJson(raw, ErrorPayload::class.java)
                    ChatEvent.Error(
                        code = err.code,
                        message = err.message
                    )
                }

                "agent_status" -> {
                    val status = gson.fromJson(raw, AgentStatusPayload::class.java)
                    ChatEvent.AgentStatus(
                        agentId = status.agentId,
                        status = AgentOnlineStatus.fromApi(status.status)
                    )
                }

                else -> {
                    Log.w(TAG, "Unknown event type: $type")
                    null
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to parse WS message: ${e.message}", e)
            null
        }
    }

    /**
     * Serialize an outgoing chat message into the JSON format expected
     * by the Agent Gateway.
     */
    fun createMessage(sessionId: String, agentId: String, text: String): String {
        return gson.toJson(
            OutgoingMessagePayload(
                type = "message",
                sessionId = sessionId,
                agentId = agentId,
                text = text
            )
        )
    }
}

// ─── Internal DTOs for WS message parsing ────────────────────────────────────

private data class IncomingMessagePayload(
    val id: String,
    @SerializedName("agent_id") val agentId: String,
    val role: String,
    val text: String,
    val timestamp: String
)

private data class TypingPayload(
    @SerializedName("agent_id") val agentId: String,
    @SerializedName("is_typing") val isTyping: Boolean
)

private data class ErrorPayload(
    val code: String,
    val message: String
)

private data class AgentStatusPayload(
    @SerializedName("agent_id") val agentId: String,
    val status: String
)

private data class OutgoingMessagePayload(
    val type: String,
    @SerializedName("session_id") val sessionId: String,
    @SerializedName("agent_id") val agentId: String,
    val text: String
)
