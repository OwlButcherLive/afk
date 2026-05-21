package com.owlbutcherlive.afk.core.network

import com.google.gson.annotations.SerializedName
import retrofit2.Response
import retrofit2.http.GET
import retrofit2.http.Query

/**
 * Retrofit interface for the Agent Gateway chat REST API.
 */
interface ChatApi {

    @GET("/chat/agents")
    suspend fun getAgents(): Response<ChatAgentsResponse>

    @GET("/chat/history")
    suspend fun getHistory(
        @Query("agent") agent: String = "default",
        @Query("limit") limit: Int = 50
    ): Response<ChatHistoryResponse>
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
