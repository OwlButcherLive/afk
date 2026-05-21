package com.owlbutcherlive.afk.domain

/**
 * Represents a single chat message displayed in the UI.
 */
data class ChatMessage(
    val id: String,
    val agentId: String,
    val role: MessageRole,
    val text: String,
    val timestamp: String
)

enum class MessageRole {
    USER,
    AGENT;

    companion object {
        fun fromApi(value: String): MessageRole = when (value.lowercase()) {
            "user" -> USER
            "agent" -> AGENT
            else -> USER
        }
    }
}
