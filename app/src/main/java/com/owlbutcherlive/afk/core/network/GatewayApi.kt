package com.owlbutcherlive.afk.core.network

import retrofit2.Response
import retrofit2.http.GET

/**
 * Minimal Agent Gateway API interface for V1.
 * Used to verify the tunnel works by hitting the remote server's health endpoint.
 */
interface GatewayApi {

    @GET("/health")
    suspend fun healthCheck(): Response<HealthResponse>

    data class HealthResponse(
        val status: String = "",
        val version: String = ""
    )
}
