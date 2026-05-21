package com.owlbutcherlive.afk.core.network

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * V2 Gateway REST API — natively exposes V2 concepts (thread, turn, item)
 * without V1 compatibility layers.
 *
 * All endpoints are under /api/v2/ for clean separation from V1 paths.
 */
interface V2GatewayApi {

    // ─── Threads ────────────────────────────────────────────────────────

    @GET("api/v2/threads")
    suspend fun listThreads(
        @Query("limit") limit: Int = 50,
    ): Response<V2ThreadListResponse>

    @GET("api/v2/threads/{threadId}")
    suspend fun getThread(
        @Path("threadId") threadId: String,
    ): Response<V2ThreadDetailResponse>

    // ─── Runtimes ───────────────────────────────────────────────────────

    @GET("api/v2/runtimes")
    suspend fun listRuntimes(): Response<V2RuntimeListResponse>
}

// ─── DTOs ───────────────────────────────────────────────────────────────

data class V2ThreadListItem(
    val id: String,
    val title: String,
    val status: String,
    val runtime_kind: String,
    val turn_count: Int,
    val last_message_preview: String = "",
    val created_at: String = "",
    val updated_at: String = "",
    val is_active: Boolean = true,
)

data class V2ThreadListResponse(
    val threads: List<V2ThreadListItem>,
)

data class V2ThreadDetailResponse(
    val id: String,
    val title: String,
    val status: String,
    val runtime_kind: String,
    val turn_count: Int,
    val active_turn_id: String = "",
    val active_turn_status: String = "",
    val items: List<Map<String, Any>> = emptyList(),
    val last_message_preview: String = "",
    val created_at: String = "",
    val updated_at: String = "",
)

data class V2RuntimeItem(
    val kind: String,
    val status: String = "unknown",
    val active_turns: Int = 0,
    val worker_count: Int = 0,
)

data class V2RuntimeListResponse(
    val runtimes: List<V2RuntimeItem>,
)
