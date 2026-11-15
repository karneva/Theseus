package com.theseus.api.common.exception;

import com.theseus.api.common.response.ApiResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.ConstraintViolationException;
import java.util.stream.Collectors;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.validation.BindException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.HandlerMethodValidationException;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

/**
 * 컨트롤러 예외를 {@link ApiResponse} 실패 형식({@code isSuccess=false, code, message})으로 통일합니다.
 * 클라이언트 입력 문제(400/404/409)는 warn으로만 남기고, 예상하지 못한 예외만 500과 스택 트레이스를 남깁니다.
 */
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

	@ExceptionHandler(BusinessException.class)
	public ResponseEntity<ApiResponse<Void>> handleBusinessException(
		BusinessException e,
		HttpServletRequest request
	) {
		log.warn(
			"[BusinessException] {} {} - Code: {}, Message: {}",
			request.getMethod(),
			request.getRequestURI(),
			e.getErrorCode().getCode(),
			e.getMessage()
		);
		return ApiResponse.onFailure(e.getErrorCode());
	}

	@ExceptionHandler({ MethodArgumentNotValidException.class, BindException.class })
	public ResponseEntity<ApiResponse<Void>> handleBindException(
		BindException e,
		HttpServletRequest request
	) {
		String detail = e
			.getBindingResult()
			.getFieldErrors()
			.stream()
			.map(error -> error.getField() + ": " + error.getDefaultMessage())
			.collect(Collectors.joining(", "));

		log.warn(
			"[ValidationException] {} {} - Detail: {}",
			request.getMethod(),
			request.getRequestURI(),
			detail
		);

		return ApiResponse.onFailure(ErrorCode.INVALID_INPUT_VALUE);
	}

	/**
	 * 본문 JSON 파싱 실패, 잘못된 enum/숫자 파라미터, 필수 파라미터·헤더 누락, 메서드 파라미터 검증 실패는
	 * 서버 오류가 아니라 잘못된 요청이므로 400으로 응답합니다.
	 */
	@ExceptionHandler({
		HttpMessageNotReadableException.class,
		MethodArgumentTypeMismatchException.class,
		MissingServletRequestParameterException.class,
		MissingRequestHeaderException.class,
		HandlerMethodValidationException.class,
		ConstraintViolationException.class,
	})
	public ResponseEntity<ApiResponse<Void>> handleBadRequest(
		Exception e,
		HttpServletRequest request
	) {
		log.warn(
			"[BadRequest] {} {} - {}: {}",
			request.getMethod(),
			request.getRequestURI(),
			e.getClass().getSimpleName(),
			e.getMessage()
		);
		return ApiResponse.onFailure(ErrorCode.INVALID_INPUT_VALUE);
	}

	@ExceptionHandler(NoResourceFoundException.class)
	public ResponseEntity<ApiResponse<Void>> handleNoResourceFoundException(
		NoResourceFoundException e,
		HttpServletRequest request
	) {
		log.warn("[NotFound] {} {}", request.getMethod(), request.getRequestURI());
		return ApiResponse.onFailure(ErrorCode.RESOURCE_NOT_FOUND);
	}

	/**
	 * 유니크 키 경합 등 서비스 검증을 통과한 뒤 DB 제약에서 걸린 경우입니다. 상세 SQL은 응답에 노출하지 않습니다.
	 */
	@ExceptionHandler(DataIntegrityViolationException.class)
	public ResponseEntity<ApiResponse<Void>> handleDataIntegrityViolationException(
		DataIntegrityViolationException e,
		HttpServletRequest request
	) {
		log.warn(
			"[DataIntegrityViolation] {} {} - {}",
			request.getMethod(),
			request.getRequestURI(),
			e.getMostSpecificCause().getMessage()
		);
		return ApiResponse.onFailure(ErrorCode.DATA_INTEGRITY_CONFLICT);
	}

	@ExceptionHandler(HttpRequestMethodNotSupportedException.class)
	public ResponseEntity<ApiResponse<Void>> handleHttpRequestMethodNotSupportedException(
		HttpRequestMethodNotSupportedException e,
		HttpServletRequest request
	) {
		log.warn(
			"[MethodNotSupported] {} {} - {}",
			request.getMethod(),
			request.getRequestURI(),
			e.getMessage()
		);
		return ApiResponse.onFailure(ErrorCode.METHOD_NOT_ALLOWED);
	}

	@ExceptionHandler(AccessDeniedException.class)
	public ResponseEntity<ApiResponse<Void>> handleAccessDeniedException(
		AccessDeniedException e,
		HttpServletRequest request
	) {
		log.warn(
			"[AccessDeniedException] {} {} - {}",
			request.getMethod(),
			request.getRequestURI(),
			e.getMessage()
		);
		return ApiResponse.onFailure(ErrorCode.HANDLE_ACCESS_DENIED);
	}

	@ExceptionHandler(ResponseStatusException.class)
	public ResponseEntity<ApiResponse<Void>> handleResponseStatusException(
		ResponseStatusException e,
		HttpServletRequest request
	) {
		ErrorCode errorCode = resolveResponseStatusErrorCode(e.getStatusCode());

		log.warn(
			"[ResponseStatusException] {} {} - Code: {}, Message: {}",
			request.getMethod(),
			request.getRequestURI(),
			errorCode.getCode(),
			getResponseStatusMessage(e)
		);

		return ApiResponse.onFailure(errorCode);
	}

	private ErrorCode resolveResponseStatusErrorCode(HttpStatusCode statusCode) {
		if (statusCode.isSameCodeAs(HttpStatus.BAD_REQUEST)) {
			return ErrorCode.INVALID_INPUT_VALUE;
		}
		if (statusCode.isSameCodeAs(HttpStatus.UNAUTHORIZED)) {
			return ErrorCode.UNAUTHORIZED;
		}
		if (statusCode.isSameCodeAs(HttpStatus.FORBIDDEN)) {
			return ErrorCode.HANDLE_ACCESS_DENIED;
		}
		if (statusCode.isSameCodeAs(HttpStatus.NOT_FOUND)) {
			return ErrorCode.RESOURCE_NOT_FOUND;
		}
		if (statusCode.isSameCodeAs(HttpStatus.METHOD_NOT_ALLOWED)) {
			return ErrorCode.METHOD_NOT_ALLOWED;
		}
		if (statusCode.isSameCodeAs(HttpStatus.CONFLICT)) {
			return ErrorCode.DATA_INTEGRITY_CONFLICT;
		}
		return ErrorCode.INTERNAL_SERVER_ERROR;
	}

	private String getResponseStatusMessage(ResponseStatusException e) {
		if (e.getReason() != null && !e.getReason().isBlank()) {
			return e.getReason();
		}

		HttpStatus httpStatus = HttpStatus.resolve(e.getStatusCode().value());
		if (httpStatus != null) {
			return httpStatus.getReasonPhrase();
		}

		return e.getStatusCode().toString();
	}

	@ExceptionHandler(Exception.class)
	public ResponseEntity<ApiResponse<Void>> handleException(Exception e, HttpServletRequest request) {
		log.error("[InternalServerError] {} {} - ", request.getMethod(), request.getRequestURI(), e);
		return ApiResponse.onFailure(ErrorCode.INTERNAL_SERVER_ERROR);
	}
}
