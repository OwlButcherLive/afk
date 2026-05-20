package com.owlbutcherlive.afk.core.network

import com.owlbutcherlive.afk.core.common.NetworkConstants
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

/**
 * Manages Retrofit HTTP client configuration.
 * All requests go to localhost on the forwarded port.
 */
object ApiClient {

    private var currentBasePort: Int = NetworkConstants.DEFAULT_LOCAL_FORWARD_PORT
    private var retrofit: Retrofit? = null
    private var okHttpClient: OkHttpClient? = null

    /**
     * Update the base URL port (called after tunnel is established).
     */
    fun configureForPort(port: Int) {
        currentBasePort = port
        retrofit = null // force rebuild
    }

    fun getOkHttpClient(): OkHttpClient {
        return okHttpClient ?: run {
            val logging = HttpLoggingInterceptor().apply {
                level = HttpLoggingInterceptor.Level.BASIC
            }

            OkHttpClient.Builder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(30, TimeUnit.SECONDS)
                .writeTimeout(30, TimeUnit.SECONDS)
                .addInterceptor(logging)
                .build()
                .also { okHttpClient = it }
        }
    }

    fun getRetrofit(): Retrofit {
        return retrofit ?: run {
            Retrofit.Builder()
                .baseUrl(NetworkConstants.baseUrl(currentBasePort))
                .client(getOkHttpClient())
                .addConverterFactory(GsonConverterFactory.create())
                .build()
                .also { retrofit = it }
        }
    }

    fun <T> createApi(apiClass: Class<T>): T = getRetrofit().create(apiClass)

    /**
     * Reset for reuse with a new tunnel.
     */
    fun reset() {
        retrofit = null
        okHttpClient = null
    }
}
