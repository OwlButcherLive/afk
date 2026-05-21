package com.owlbutcherlive.afk.domain

/**
 * Represents a chat session (conversation) on the remote gateway.
 * Server is the source of truth — this is a local convenience model.
 */
data class ChatSession(
    val id: String,
    val agentId: String,
    val title: String,
    val lastMessagePreview: String = "",
    val updatedAt: String
)
