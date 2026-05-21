package com.owlbutcherlive.afk.core.network

import com.google.gson.annotations.SerializedName
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * Retrofit interface for the Agent Gateway chat REST API.
 */
interface ChatApi {

    @GET("/chat/agents")
    suspend fun getAgents(): Response<ChatAgentsResponse>

    @GET("/chat/history")
    suspend fun getHistory(
        @Query("session") session: String? = null,
        @Query("agent") agent: String? = "default",
        @Query("limit") limit: Int = 50
    ): Response<ChatHistoryResponse>

    @GET("/chat/sessions")
    suspend fun getSessions(): Response<ChatSessionsResponse>

    @POST("/chat/sessions")
    suspend fun createSession(@Body request: CreateSessionRequest): Response<ChatSessionResponse>

    @GET("/chat/sessions/{sessionId}")
    suspend fun getSession(@Path("sessionId") sessionId: String): Response<ChatSessionResponse>
}

// ─── REST response DTOs ─────────────────────────────────────────────────────

data class ChatAgentsResponse(
    val agents: List<AgentDto>
)

data class AgentDto(
    val id: String,
    val name: String,
    val status: String
)

data class ChatHistoryResponse(
    val messages: List<MessageDto>
)

data class MessageDto(
    val id: String,
    @SerializedName("agent_id")
    val agentId: String,
    val role: String,
    val text: String,
    val timestamp: String
)

// ─── Session DTOs ────────────────────────────────────────────────────────────

data class ChatSessionsResponse(
    val sessions: List<SessionDto>
)

data class SessionDto(
    val id: String,
    @SerializedName("agent_id")
    val agentId: String,
    val title: String,
    @SerializedName("last_message_preview")
    val lastMessagePreview: String = "",
    @SerializedName("updated_at")
    val updatedAt: String
)

data class ChatSessionResponse(
    val id: String,
    @SerializedName("agent_id")
    val agentId: String,
    val title: String,
    @SerializedName("updated_at")
    val updatedAt: String
)

data class CreateSessionRequest(
    @SerializedName("agent_id")
    val agentId: String
)
