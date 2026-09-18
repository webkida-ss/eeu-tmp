// Classic-script runtime for enforcing the generated extension API contract.
((global) => {
  'use strict';

  const uncurryThis = Function.bind.bind(Function.call);
  const objectCreate = Object.create;
  const objectDefineProperty = Object.defineProperty;
  const objectEntries = Object.entries;
  const objectFreeze = Object.freeze;
  const objectKeys = Object.keys;
  const objectIsPrototypeOf = uncurryThis(Object.prototype.isPrototypeOf);
  const hasOwn = uncurryThis(Object.prototype.hasOwnProperty);
  const arrayFrom = Array.from;
  const arrayIsArray = Array.isArray;
  const arrayEvery = uncurryThis(Array.prototype.every);
  const arrayIncludes = uncurryThis(Array.prototype.includes);
  const arrayJoin = uncurryThis(Array.prototype.join);
  const arrayMap = uncurryThis(Array.prototype.map);
  const arrayPush = uncurryThis(Array.prototype.push);
  const arraySome = uncurryThis(Array.prototype.some);
  const arraySort = uncurryThis(Array.prototype.sort);
  const regexpTest = uncurryThis(RegExp.prototype.test);
  const stringCodePointAt = uncurryThis(String.prototype.codePointAt);
  const stringEndsWith = uncurryThis(String.prototype.endsWith);
  const stringSlice = uncurryThis(String.prototype.slice);
  const stringStartsWith = uncurryThis(String.prototype.startsWith);
  const stringToLowerCase = uncurryThis(String.prototype.toLowerCase);
  const safeError = Error;
  const safeHeadersPrototype = Headers.prototype;
  const safeNumber = Number;
  const safeNumberIsInteger = Number.isInteger;
  const safeString = String;
  const safeURLSearchParams = URLSearchParams;
  const headersGet = uncurryThis(safeHeadersPrototype.get);
  const searchParamsAppend = uncurryThis(safeURLSearchParams.prototype.append);
  const searchParamsToString = uncurryThis(safeURLSearchParams.prototype.toString);
  const tokenCharacter = /^[!#$%&'*+\-.^_`|~0-9A-Za-z]$/;
  const controlCharacter = /[\u0000-\u001f\u007f]/;
  const CONTRACT_ERROR_MESSAGE = 'The server returned an unexpected API response.';

  const OPERATION_FIELD_CONSUMERS = objectCreate(null);
  OPERATION_FIELD_CONSUMERS.method = (operation) => operation.method;
  OPERATION_FIELD_CONSUMERS.path = (operation) => operation.path;
  OPERATION_FIELD_CONSUMERS.queryParameters = (operation) => operation.queryParameters;
  OPERATION_FIELD_CONSUMERS.responses = (operation) => operation.responses;
  OPERATION_FIELD_CONSUMERS.successStatuses = (operation) => operation.successStatuses;
  objectFreeze(OPERATION_FIELD_CONSUMERS);
  const consumedOperationFields = objectKeys(OPERATION_FIELD_CONSUMERS);
  arraySort(consumedOperationFields);
  objectFreeze(consumedOperationFields);

  function sameFields(left, right) {
    return (
      left.length === right.length && arrayEvery(left, (field, index) => field === right[index])
    );
  }

  function operationIdFor(operation) {
    const operations = global.UntangleApiContract?.operations || objectCreate(null);
    const entries = objectEntries(operations);
    for (let index = 0; index < entries.length; index += 1) {
      if (entries[index][1] === operation) return entries[index][0];
    }
    return 'unknownOperation';
  }

  class ApiContractViolationError extends safeError {
    constructor(operationId, reason) {
      super(CONTRACT_ERROR_MESSAGE);
      this.name = 'ApiContractViolationError';
      this.operationId = operationId;
      this.reason = reason;
      this.retryable = false;
    }
  }

  class ApiNetworkError extends safeError {
    constructor(operation) {
      super('The API request could not reach the server.');
      this.name = 'ApiNetworkError';
      this.operationId = operationIdFor(operation);
      this.retryable = true;
    }
  }

  class ApiDeclaredError extends safeError {
    constructor(operation, publicMessage) {
      super(publicMessage);
      this.name = 'ApiDeclaredError';
      this.operationId = operationIdFor(operation);
      this.retryable = false;
    }
  }

  class ApiBodyError extends safeError {
    constructor(operation) {
      super('The API response body could not be read.');
      this.name = 'ApiBodyError';
      this.operationId = operationIdFor(operation);
      this.retryable = false;
    }
  }

  function verifyGeneratedOperationFields() {
    const generatedFields = global.UntangleApiContract?.operationFields;
    const operations = global.UntangleApiContract?.operations;
    if (!arrayIsArray(generatedFields) || !operations) {
      throw new safeError('Generated API contract field metadata is missing.');
    }
    if (!sameFields(generatedFields, consumedOperationFields)) {
      throw new safeError(
        `Generated API operation fields do not match consumer fields: ` +
          `generated=${arrayJoin(generatedFields, ',')} ` +
          `consumed=${arrayJoin(consumedOperationFields, ',')}`,
      );
    }
    const entries = objectEntries(operations);
    for (let index = 0; index < entries.length; index += 1) {
      const operationId = entries[index][0];
      const actualFields = objectKeys(entries[index][1]);
      arraySort(actualFields);
      if (!sameFields(actualFields, generatedFields)) {
        throw new safeError(
          `Generated API operation ${operationId} has inconsistent fields: ` +
            arrayJoin(actualFields, ','),
        );
      }
    }
  }

  verifyGeneratedOperationFields();

  function operationField(operation, field) {
    if (
      !operation ||
      typeof operation !== 'object' ||
      !hasOwn(OPERATION_FIELD_CONSUMERS, field) ||
      !hasOwn(operation, field)
    ) {
      throw new ApiContractViolationError(operationIdFor(operation), 'invalid-operation-shape');
    }
    return OPERATION_FIELD_CONSUMERS[field](operation);
  }

  function contentTypeHeader(headers) {
    if (!headers) return null;
    if (objectIsPrototypeOf(safeHeadersPrototype, headers)) {
      return headersGet(headers, 'content-type');
    }
    const entries = objectEntries(headers);
    const values = [];
    for (let index = 0; index < entries.length; index += 1) {
      if (stringToLowerCase(entries[index][0]) === 'content-type') {
        arrayPush(values, safeString(entries[index][1]));
      }
    }
    return values.length ? arrayJoin(values, ',') : null;
  }

  function parseContentType(value) {
    if (
      typeof value !== 'string' ||
      regexpTest(controlCharacter, value) ||
      arraySome(arrayFrom(value), (character) => stringCodePointAt(character, 0) > 0xff)
    )
      return null;

    let index = 0;
    const skipSpaces = () => {
      while (value[index] === ' ') index += 1;
    };
    const readToken = () => {
      const start = index;
      while (index < value.length && regexpTest(tokenCharacter, value[index])) index += 1;
      return stringSlice(value, start, index);
    };

    skipSpaces();
    const type = readToken();
    if (!type || value[index] !== '/') return null;
    index += 1;
    const subtype = readToken();
    if (!subtype) return null;
    const parameters = objectCreate(null);

    while (true) {
      skipSpaces();
      if (index === value.length) {
        return `${stringToLowerCase(type)}/${stringToLowerCase(subtype)}`;
      }
      if (value[index] !== ';') return null;
      index += 1;
      skipSpaces();
      const name = stringToLowerCase(readToken());
      if (!name) return null;
      skipSpaces();
      if (value[index] !== '=') return null;
      index += 1;
      skipSpaces();

      let parameterValue = '';
      if (value[index] === '"') {
        index += 1;
        let closed = false;
        while (index < value.length) {
          const character = value[index];
          if (character === '"') {
            index += 1;
            closed = true;
            break;
          }
          if (character === '\\') {
            index += 1;
            if (index >= value.length) return null;
            parameterValue += value[index];
            index += 1;
            continue;
          }
          parameterValue += character;
          index += 1;
        }
        if (!closed) return null;
      } else {
        parameterValue = readToken();
        if (!parameterValue) return null;
      }
      if (hasOwn(parameters, name) && parameters[name] !== parameterValue) return null;
      parameters[name] = parameterValue;
    }
  }

  function inspectResponse(operation, response) {
    const operationId = operationIdFor(operation);
    if (!operation || typeof operation !== 'object') {
      throw new ApiContractViolationError(operationId, 'missing-generated-operation');
    }
    if (!response || !safeNumberIsInteger(safeNumber(response.status))) {
      throw new ApiContractViolationError(operationId, 'missing-http-status');
    }

    const status = safeString(response.status);
    const responses = operationField(operation, 'responses');
    if (!hasOwn(responses, status)) {
      throw new ApiContractViolationError(operationId, `undeclared-status-${status}`);
    }
    const declaredMediaTypes = responses[status];
    if (!arrayIsArray(declaredMediaTypes)) {
      throw new ApiContractViolationError(operationId, 'invalid-response-contract');
    }

    const rawContentType = contentTypeHeader(response.headers);
    const actualMediaType = rawContentType === null ? null : parseContentType(rawContentType);
    const normalizedDeclared = arrayMap(declaredMediaTypes, (mediaType) =>
      stringToLowerCase(mediaType),
    );
    if (normalizedDeclared.length === 0) {
      if (rawContentType !== null) {
        throw new ApiContractViolationError(operationId, `unexpected-media-status-${status}`);
      }
    } else if (rawContentType === null) {
      throw new ApiContractViolationError(operationId, `missing-content-type-status-${status}`);
    } else if (!actualMediaType) {
      throw new ApiContractViolationError(operationId, `malformed-content-type-status-${status}`);
    } else if (!arrayIncludes(normalizedDeclared, actualMediaType)) {
      throw new ApiContractViolationError(operationId, `undeclared-media-status-${status}`);
    }

    return objectFreeze({
      status,
      mediaType: actualMediaType,
      success: arrayIncludes(operationField(operation, 'successStatuses'), status),
    });
  }

  function methodFor(operation) {
    return operationField(operation, 'method');
  }

  function buildPath(operation, query = undefined) {
    const operationId = operationIdFor(operation);
    const path = operationField(operation, 'path');
    const metadata = operationField(operation, 'queryParameters');
    const supplied = query === undefined || query === null ? objectCreate(null) : query;
    if (typeof supplied !== 'object' || arrayIsArray(supplied)) {
      throw new ApiContractViolationError(operationId, 'invalid-query-object');
    }

    const allowed = objectCreate(null);
    for (let index = 0; index < metadata.length; index += 1) {
      allowed[metadata[index].name] = metadata[index];
    }
    const suppliedKeys = objectKeys(supplied);
    for (let index = 0; index < suppliedKeys.length; index += 1) {
      if (!hasOwn(allowed, suppliedKeys[index])) {
        throw new ApiContractViolationError(operationId, 'unknown-query-parameter');
      }
    }

    const search = new safeURLSearchParams();
    for (let index = 0; index < metadata.length; index += 1) {
      const parameter = metadata[index];
      const present = hasOwn(supplied, parameter.name);
      const value = present ? supplied[parameter.name] : undefined;
      if (!present || value === undefined || value === null) {
        if (parameter.required) {
          throw new ApiContractViolationError(operationId, 'missing-required-query-parameter');
        }
        continue;
      }
      if (parameter.style !== 'form') {
        throw new ApiContractViolationError(operationId, 'unsupported-query-style');
      }
      const values = arrayIsArray(value) ? value : [value];
      if (arrayIsArray(value) && (!parameter.repeat || !parameter.explode)) {
        throw new ApiContractViolationError(operationId, 'invalid-repeated-query');
      }
      for (let valueIndex = 0; valueIndex < values.length; valueIndex += 1) {
        const item = values[valueIndex];
        if (item !== null && typeof item === 'object') {
          throw new ApiContractViolationError(operationId, 'invalid-query-value');
        }
        searchParamsAppend(search, parameter.name, safeString(item));
      }
    }
    const encoded = searchParamsToString(search);
    return encoded ? `${path}?${encoded}` : path;
  }

  async function consumeResponse(operation, response, readErrorMessage, fallback) {
    const result = inspectResponse(operation, response);
    if (!result.success) {
      throw new ApiDeclaredError(operation, await readErrorMessage(response, fallback));
    }
    if (!result.mediaType) return undefined;
    try {
      if (result.mediaType === 'application/json' || stringEndsWith(result.mediaType, '+json'))
        return await response.json();
      if (stringStartsWith(result.mediaType, 'text/')) return await response.text();
      return await response.arrayBuffer();
    } catch {
      throw new ApiBodyError(operation);
    }
  }

  const namespace = objectFreeze({
    ApiBodyError,
    ApiContractViolationError,
    ApiDeclaredError,
    ApiNetworkError,
    buildPath,
    consumedOperationFields,
    consumeResponse,
    inspectResponse,
    methodFor,
    parseContentType,
  });

  objectDefineProperty(global, 'UntangleApiContractRuntime', {
    value: namespace,
    writable: false,
    configurable: false,
    enumerable: true,
  });
})(globalThis);
