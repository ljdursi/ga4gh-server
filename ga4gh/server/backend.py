"""
Module responsible for handling protocol requests and returning
responses.
"""
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import ga4gh.server.datamodel as datamodel
import ga4gh.server.exceptions as exceptions
import ga4gh.server.paging as paging
import ga4gh.server.response_builder as response_builder

import ga4gh.schemas.protocol as protocol


class Backend(object):
    """
    Backend for handling the server requests.
    This class provides methods for all of the GA4GH protocol end points.
    """
    def __init__(self, dataRepository):
        self._requestValidation = False
        self._defaultPageSize = 100
        self._maxResponseLength = 2**20  # 1 MiB
        self._dataRepository = dataRepository

    def getDataRepository(self):
        """
        Get the data repository used by this backend
        """
        return self._dataRepository

    def setRequestValidation(self, requestValidation):
        """
        Set enabling request validation
        """
        self._requestValidation = requestValidation

    def setDefaultPageSize(self, defaultPageSize):
        """
        Sets the default page size for request to the specified value.
        """
        self._defaultPageSize = defaultPageSize

    def setMaxResponseLength(self, maxResponseLength):
        """
        Sets the approximate maximum response length to the specified
        value.
        """
        self._maxResponseLength = maxResponseLength

    def startProfile(self):
        """
        Profiling hook. Called at the start of the runSearchRequest method
        and allows for detailed profiling of search performance.
        """
        pass

    def endProfile(self):
        """
        Profiling hook. Called at the end of the runSearchRequest method.
        """
        pass

    ###########################################################
    #
    # Iterators over the data hierarchy. These methods help to
    # implement the search endpoints by providing iterators
    # over the objects to be returned to the client.
    #
    ###########################################################

    def _topLevelObjectGenerator(self, request, numObjects, getByIndexMethod):
        """
        Returns a generator over the results for the specified request, which
        is over a set of objects of the specified size. The objects are
        returned by call to the specified method, which must take a single
        integer as an argument. The returned generator yields a sequence of
        (object, nextPageToken) pairs, which allows this iteration to be picked
        up at any point.
        """
        currentIndex = 0
        if request.page_token:
            currentIndex, = paging._parsePageToken(
                request.page_token, 1)
        while currentIndex < numObjects:
            object_ = getByIndexMethod(currentIndex)
            currentIndex += 1
            nextPageToken = None
            if currentIndex < numObjects:
                nextPageToken = str(currentIndex)
            yield object_.toProtocolElement(), nextPageToken

    def _protocolObjectGenerator(self, request, numObjects, getByIndexMethod):
        """
        Returns a generator over the results for the specified request, from
        a set of protocol objects of the specified size. The objects are
        returned by call to the specified method, which must take a single
        integer as an argument. The returned generator yields a sequence of
        (object, nextPageToken) pairs, which allows this iteration to be picked
        up at any point.
        """
        currentIndex = 0
        if request.page_token:
            currentIndex, = paging._parsePageToken(
                request.page_token, 1)
        while currentIndex < numObjects:
            object_ = getByIndexMethod(currentIndex)
            currentIndex += 1
            nextPageToken = None
            if currentIndex < numObjects:
                nextPageToken = str(currentIndex)
            yield object_, nextPageToken

    def _protocolListGenerator(self, request, objectList):
        """
        Returns a generator over the objects in the specified list using
        _protocolObjectGenerator to generate page tokens.
        """
        return self._protocolObjectGenerator(
            request, len(objectList), lambda index: objectList[index])

    def _objectListGenerator(self, request, objectList):
        """
        Returns a generator over the objects in the specified list using
        _topLevelObjectGenerator to generate page tokens.
        """
        return self._topLevelObjectGenerator(
            request, len(objectList), lambda index: objectList[index])

    def datasetsGenerator(self, request):
        """
        Returns a generator over the (dataset, nextPageToken) pairs
        defined by the specified request
        """
        return self._topLevelObjectGenerator(
            request, self.getDataRepository().getNumDatasets(),
            self.getDataRepository().getDatasetByIndex)

    def experimentsGenerator(self, request):
        """
        Returns a generator over the (experiment, nextPageToken) pairs
        defined by the specified request
        TODO: This should really be under the appropriate biosamples, but
        for now..
        """
        return self._topLevelObjectGenerator(
            request, self.getDataRepository().getNumExperiments(),
            self.getDataRepository().getExperimentByIndex)

    def biosamplesGenerator(self, request):
        dataset = self.getDataRepository().getDataset(request.dataset_id)
        results = []
        for obj in dataset.getBiosamples():
            include = True
            if request.name:
                if request.name != obj.getLocalId():
                    include = False
            if request.individual_id:
                if request.individual_id != obj.getIndividualId():
                    include = False
            if include:
                results.append(obj)
        return self._objectListGenerator(request, results)

    def individualsGenerator(self, request):
        dataset = self.getDataRepository().getDataset(request.dataset_id)
        results = []
        for obj in dataset.getIndividuals():
            include = True
            if request.name:
                if request.name != obj.getLocalId():
                    include = False
            if include:
                results.append(obj)
        return self._objectListGenerator(request, results)

    def phenotypeAssociationSetsGenerator(self, request):
        """
        Returns a generator over the (phenotypeAssociationSet, nextPageToken)
        pairs defined by the specified request
        """
        dataset = self.getDataRepository().getDataset(request.dataset_id)
        return self._topLevelObjectGenerator(
            request, dataset.getNumPhenotypeAssociationSets(),
            dataset.getPhenotypeAssociationSetByIndex)

    def readGroupSetsGenerator(self, request):
        """
        Returns a generator over the (readGroupSet, nextPageToken) pairs
        defined by the specified request.
        """
        dataset = self.getDataRepository().getDataset(request.dataset_id)
        return self._readGroupSetsGenerator(
            request, dataset.getNumReadGroupSets(),
            dataset.getReadGroupSetByIndex)

    def _readGroupSetsGenerator(self, request, numObjects, getByIndexMethod):
        """
        Returns a generator over the results for the specified request, which
        is over a set of objects of the specified size. The objects are
        returned by call to the specified method, which must take a single
        integer as an argument. The returned generator yields a sequence of
        (object, nextPageToken) pairs, which allows this iteration to be picked
        up at any point.
        """
        currentIndex = 0
        if request.page_token:
            currentIndex, = paging._parsePageToken(
                request.page_token, 1)
        while currentIndex < numObjects:
            obj = getByIndexMethod(currentIndex)
            include = True
            rgsp = obj.toProtocolElement()
            if request.name and request.name != obj.getLocalId():
                include = False
            if request.biosample_id and include:
                rgsp.ClearField(b"read_groups")
                for readGroup in obj.getReadGroups():
                    if request.biosample_id == readGroup.getBiosampleId():
                        rgsp.read_groups.extend(
                            [readGroup.toProtocolElement()])
                # If none of the biosamples match and the readgroupset
                # contains reagroups, don't include in the response
                if len(rgsp.read_groups) == 0 and \
                        len(obj.getReadGroups()) != 0:
                    include = False
            currentIndex += 1
            nextPageToken = None
            if currentIndex < numObjects:
                nextPageToken = str(currentIndex)
            if include:
                yield rgsp, nextPageToken

    def referenceSetsGenerator(self, request):
        """
        Returns a generator over the (referenceSet, nextPageToken) pairs
        defined by the specified request.
        """
        results = []
        for obj in self.getDataRepository().getReferenceSets():
            include = True
            if request.md5checksum:
                if request.md5checksum != obj.getMd5Checksum():
                    include = False
            if request.accession:
                if request.accession not in obj.getSourceAccessions():
                    include = False
            if request.assembly_id:
                if request.assembly_id != obj.getAssemblyId():
                    include = False
            if include:
                results.append(obj)
        return self._objectListGenerator(request, results)

    def referencesGenerator(self, request):
        """
        Returns a generator over the (reference, nextPageToken) pairs
        defined by the specified request.
        """
        referenceSet = self.getDataRepository().getReferenceSet(
            request.reference_set_id)
        results = []
        for obj in referenceSet.getReferences():
            include = True
            if request.md5checksum:
                if request.md5checksum != obj.getMd5Checksum():
                    include = False
            if request.accession:
                if request.accession not in obj.getSourceAccessions():
                    include = False
            if include:
                results.append(obj)
        return self._objectListGenerator(request, results)

    def variantSetsGenerator(self, request):
        """
        Returns a generator over the (variantSet, nextPageToken) pairs defined
        by the specified request.
        """
        dataset = self.getDataRepository().getDataset(request.dataset_id)
        return self._topLevelObjectGenerator(
            request, dataset.getNumVariantSets(),
            dataset.getVariantSetByIndex)

    def variantAnnotationSetsGenerator(self, request):
        """
        Returns a generator over the (variantAnnotationSet, nextPageToken)
        pairs defined by the specified request.
        """
        compoundId = datamodel.VariantSetCompoundId.parse(
            request.variant_set_id)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        variantSet = dataset.getVariantSet(request.variant_set_id)
        return self._topLevelObjectGenerator(
            request, variantSet.getNumVariantAnnotationSets(),
            variantSet.getVariantAnnotationSetByIndex)

    def readsGenerator(self, request):
        """
        Returns a generator over the (read, nextPageToken) pairs defined
        by the specified request
        """
        if not request.reference_id:
            raise exceptions.UnmappedReadsNotSupported()
        if len(request.read_group_ids) < 1:
            raise exceptions.BadRequestException(
                "At least one readGroupId must be specified")
        elif len(request.read_group_ids) == 1:
            return self._readsGeneratorSingle(request)
        else:
            return self._readsGeneratorMultiple(request)

    def _readsGeneratorSingle(self, request):
        compoundId = datamodel.ReadGroupCompoundId.parse(
            request.read_group_ids[0])
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        readGroupSet = dataset.getReadGroupSet(compoundId.read_group_set_id)
        referenceSet = readGroupSet.getReferenceSet()
        if referenceSet is None:
            raise exceptions.ReadGroupSetNotMappedToReferenceSetException(
                    readGroupSet.getId())
        reference = referenceSet.getReference(request.reference_id)
        readGroup = readGroupSet.getReadGroup(compoundId.read_group_id)
        intervalIterator = paging.ReadsIntervalIterator(
            request, readGroup, reference)
        return intervalIterator

    def _readsGeneratorMultiple(self, request):
        compoundId = datamodel.ReadGroupCompoundId.parse(
            request.read_group_ids[0])
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        readGroupSet = dataset.getReadGroupSet(compoundId.read_group_set_id)
        referenceSet = readGroupSet.getReferenceSet()
        if referenceSet is None:
            raise exceptions.ReadGroupSetNotMappedToReferenceSetException(
                    readGroupSet.getId())
        reference = referenceSet.getReference(request.reference_id)
        readGroupIds = readGroupSet.getReadGroupIds()
        if set(readGroupIds) != set(request.read_group_ids):
            raise exceptions.BadRequestException(
                "If multiple readGroupIds are specified, "
                "they must be all of the readGroupIds in a ReadGroupSet")
        intervalIterator = paging.ReadsIntervalIterator(
            request, readGroupSet, reference)
        return intervalIterator

    def variantsGenerator(self, request):
        """
        Returns a generator over the (variant, nextPageToken) pairs defined
        by the specified request.
        """
        compoundId = datamodel.VariantSetCompoundId \
            .parse(request.variant_set_id)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        variantSet = dataset.getVariantSet(compoundId.variant_set_id)
        intervalIterator = paging.VariantsIntervalIterator(
            request, variantSet)
        return intervalIterator

    def genotypeMatrixGenerator(self, request):
        """
        Returns a generator over the (genotypematrix, nextPageToken) pairs
        defined by the specified request.
        """
        compoundId = datamodel.VariantSetCompoundId \
            .parse(request.variant_set_id)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        variantSet = dataset.getVariantSet(compoundId.variant_set_id)
        intervalIterator = paging.GenotypesIntervalIterator(
            request, variantSet)
        return intervalIterator

    def variantAnnotationsGenerator(self, request):
        """
        Returns a generator over the (variantAnnotaitons, nextPageToken) pairs
        defined by the specified request.
        """
        compoundId = datamodel.VariantAnnotationSetCompoundId.parse(
            request.variant_annotation_set_id)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        variantSet = dataset.getVariantSet(compoundId.variant_set_id)
        variantAnnotationSet = variantSet.getVariantAnnotationSet(
            request.variant_annotation_set_id)
        iterator = paging.VariantAnnotationsIntervalIterator(
            request, variantAnnotationSet)
        return iterator

    def featuresGenerator(self, request):
        """
        Returns a generator over the (features, nextPageToken) pairs
        defined by the (JSON string) request.
        """
        compoundId = None
        parentId = None
        if request.feature_set_id != "":
            compoundId = datamodel.FeatureSetCompoundId.parse(
                request.feature_set_id)
        if request.parent_id != "":
            compoundParentId = datamodel.FeatureCompoundId.parse(
                request.parent_id)
            parentId = compoundParentId.featureId
            # A client can optionally specify JUST the (compound) parentID,
            # and the server needs to derive the dataset & featureSet
            # from this (compound) parentID.
            if compoundId is None:
                compoundId = compoundParentId
            else:
                # check that the dataset and featureSet of the parent
                # compound ID is the same as that of the featureSetId
                mismatchCheck = (
                    compoundParentId.dataset_id != compoundId.dataset_id or
                    compoundParentId.feature_set_id !=
                    compoundId.feature_set_id)
                if mismatchCheck:
                    raise exceptions.ParentIncompatibleWithFeatureSet()

        if compoundId is None:
            raise exceptions.FeatureSetNotSpecifiedException()

        dataset = self.getDataRepository().getDataset(
            compoundId.dataset_id)
        featureSet = dataset.getFeatureSet(compoundId.feature_set_id)
        iterator = paging.FeaturesIterator(
            request, featureSet, parentId)
        return iterator

    def continuousGenerator(self, request):
        """
        Returns a generator over the (continuous, nextPageToken) pairs
        defined by the (JSON string) request.
        """
        compoundId = None
        if request.continuous_set_id != "":
            compoundId = datamodel.ContinuousSetCompoundId.parse(
                request.continuous_set_id)
        if compoundId is None:
            raise exceptions.ContinuousSetNotSpecifiedException()

        dataset = self.getDataRepository().getDataset(
            compoundId.dataset_id)
        continuousSet = dataset.getContinuousSet(request.continuous_set_id)
        iterator = paging.ContinuousIterator(request, continuousSet)
        return iterator

    def phenotypesGenerator(self, request):
        """
        Returns a generator over the (phenotypes, nextPageToken) pairs
        defined by the (JSON string) request
        """
        # TODO make paging work using SPARQL?
        compoundId = datamodel.PhenotypeAssociationSetCompoundId.parse(
            request.phenotype_association_set_id)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        phenotypeAssociationSet = dataset.getPhenotypeAssociationSet(
            compoundId.phenotypeAssociationSetId)
        associations = phenotypeAssociationSet.getAssociations(request)
        phenotypes = [association.phenotype for association in associations]
        return self._protocolListGenerator(
            request, phenotypes)

    def genotypesPhenotypesGenerator(self, request):
        """
        Returns a generator over the (phenotypes, nextPageToken) pairs
        defined by the (JSON string) request
        """
        # TODO make paging work using SPARQL?
        compoundId = datamodel.PhenotypeAssociationSetCompoundId.parse(
            request.phenotype_association_set_id)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        phenotypeAssociationSet = dataset.getPhenotypeAssociationSet(
            compoundId.phenotypeAssociationSetId)
        featureSets = dataset.getFeatureSets()
        annotationList = phenotypeAssociationSet.getAssociations(
            request, featureSets)
        return self._protocolListGenerator(request, annotationList)

    def callSetsGenerator(self, request):
        """
        Returns a generator over the (callSet, nextPageToken) pairs defined
        by the specified request.
        """
        compoundId = datamodel.VariantSetCompoundId.parse(
            request.variant_set_id)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        variantSet = dataset.getVariantSet(compoundId.variant_set_id)
        results = []
        for obj in variantSet.getCallSets():
            include = True
            if request.name:
                if request.name != obj.getLocalId():
                    include = False
            if request.biosample_id:
                if request.biosample_id != obj.getBiosampleId():
                    include = False
            if include:
                results.append(obj)
        return self._objectListGenerator(request, results)

    def featureSetsGenerator(self, request):
        """
        Returns a generator over the (featureSet, nextPageToken) pairs
        defined by the specified request.
        """
        dataset = self.getDataRepository().getDataset(request.dataset_id)
        return self._topLevelObjectGenerator(
            request, dataset.getNumFeatureSets(),
            dataset.getFeatureSetByIndex)

    def continuousSetsGenerator(self, request):
        """
        Returns a generator over the (continuousSet, nextPageToken) pairs
        defined by the specified request.
        """
        dataset = self.getDataRepository().getDataset(request.dataset_id)
        return self._topLevelObjectGenerator(
            request, dataset.getNumContinuousSets(),
            dataset.getContinuousSetByIndex)

    def rnaQuantificationSetsGenerator(self, request):
        """
        Returns a generator over the (rnaQuantificationSet, nextPageToken)
        pairs defined by the specified request.
        """
        dataset = self.getDataRepository().getDataset(request.dataset_id)
        return self._topLevelObjectGenerator(
            request, dataset.getNumRnaQuantificationSets(),
            dataset.getRnaQuantificationSetByIndex)

    def rnaQuantificationsGenerator(self, request):
        """
        Returns a generator over the (rnaQuantification, nextPageToken) pairs
        defined by the specified request.
        """
        if len(request.rna_quantification_set_id) < 1:
            raise exceptions.BadRequestException(
                "Rna Quantification Set Id must be specified")
        else:
            compoundId = datamodel.RnaQuantificationSetCompoundId.parse(
                request.rna_quantification_set_id)
            dataset = self.getDataRepository().getDataset(
                compoundId.dataset_id)
            rnaQuantSet = dataset.getRnaQuantificationSet(
                compoundId.rna_quantification_set_id)
        results = []
        for obj in rnaQuantSet.getRnaQuantifications():
            include = True
            if request.biosample_id:
                if request.biosample_id != obj.getBiosampleId():
                    include = False
            if include:
                results.append(obj)
        return self._objectListGenerator(request, results)

    def expressionLevelsGenerator(self, request):
        """
        Returns a generator over the (expressionLevel, nextPageToken) pairs
        defined by the specified request.

        Currently only supports searching over a specified rnaQuantification
        """
        rnaQuantificationId = request.rna_quantification_id
        compoundId = datamodel.RnaQuantificationCompoundId.parse(
            request.rna_quantification_id)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        rnaQuantSet = dataset.getRnaQuantificationSet(
            compoundId.rna_quantification_set_id)
        rnaQuant = rnaQuantSet.getRnaQuantification(rnaQuantificationId)
        rnaQuantificationId = rnaQuant.getLocalId()
        iterator = paging.ExpressionLevelsIterator(
            request, rnaQuant)
        return iterator

    ###########################################################
    #
    # Public API methods. Each of these methods implements the
    # corresponding API end point, and return data ready to be
    # written to the wire.
    #
    ###########################################################

    def runGetRequest(self, obj, return_mimetype="application/json"):
        """
        Runs a get request by converting the specified datamodel
        object into its protocol representation.
        """
        protocolElement = obj.toProtocolElement()
        data = protocol.serialize(protocolElement, return_mimetype)
        return data

    def runSearchRequest(
            self, requestStr, requestClass, responseClass, objectGenerator,
            return_mimetype="application/json"):
        """
        Runs the specified request. The request is a string containing
        a JSON representation of an instance of the specified requestClass.
        We return a string representation of an instance of the
        specified responseClass in return_mimetype format. Objects
        are filled into the page list using the specified object
        generator, which must return (object, nextPageToken) pairs,
        and be able to resume iteration from any point using the
        nextPageToken attribute of the request object.
        """
        self.startProfile()
        try:
            request = protocol.fromJson(requestStr, requestClass)
        except protocol.json_format.ParseError:
            raise exceptions.InvalidJsonException(requestStr)
        # TODO How do we detect when the page size is not set?
        if not request.page_size:
            request.page_size = self._defaultPageSize
        if request.page_size < 0:
            raise exceptions.BadPageSizeException(request.page_size)
        responseBuilder = response_builder.SearchResponseBuilder(
            responseClass, request.page_size, self._maxResponseLength,
            return_mimetype)
        nextPageToken = None
        for obj, nextPageToken in objectGenerator(request):
            responseBuilder.addValue(obj)
            if responseBuilder.isFull():
                break
        responseBuilder.setNextPageToken(nextPageToken)
        responseString = responseBuilder.getSerializedResponse()
        self.endProfile()
        return responseString

    def runListReferenceBases(self, requestJson,
                              return_mimetype="application/json"):
        """
        Runs a listReferenceBases request for the specified ID and
        request arguments.
        """
        # In the case when an empty post request is made to the endpoint
        # we instantiate an empty ListReferenceBasesRequest.
        if not requestJson:
            request = protocol.ListReferenceBasesRequest()
        else:
            try:
                request = protocol.fromJson(
                    requestJson,
                    protocol.ListReferenceBasesRequest)
            except protocol.json_format.ParseError:
                raise exceptions.InvalidJsonException(requestJson)
        compoundId = datamodel.ReferenceCompoundId.parse(request.reference_id)
        referenceSet = self.getDataRepository().getReferenceSet(
            compoundId.reference_set_id)
        reference = referenceSet.getReference(request.reference_id)
        start = request.start
        end = request.end
        if end == 0:  # assume meant "get all"
            end = reference.getLength()
        if request.page_token:
            pageTokenStr = request.page_token
            start = paging._parsePageToken(pageTokenStr, 1)[0]

        chunkSize = self._maxResponseLength
        nextPageToken = None
        if start + chunkSize < end:
            end = start + chunkSize
            nextPageToken = str(start + chunkSize)
        sequence = reference.getBases(start, end)

        # build response
        response = protocol.ListReferenceBasesResponse()
        response.offset = start
        response.sequence = sequence
        if nextPageToken:
            response.next_page_token = nextPageToken
        return protocol.serialize(response, return_mimetype)

    def runSearchGenotypesRequest(self, requestStr,
                                  return_mimetype="application/json"):
        """
        Runs a searchGenotypes request for the specified
        request arguments.

        Can't just use runSearchRequest because we're appending
        multiple things - the variants and the genotype matrix
        """
        self.startProfile()
        requestClass = protocol.SearchGenotypesRequest
        responseClass = protocol.SearchGenotypesResponse
        objectGenerator = self.genotypeMatrixGenerator

        try:
            request = protocol.fromJson(requestStr, requestClass)
        except protocol.json_format.ParseError:
            raise exceptions.InvalidJsonException(requestStr)

        response = responseClass()
        response.genotypes.nvariants = 0
        response.genotypes.nindividuals = 0

        # to heck with paging for now
        # and to heck with call set ids too

        genotyperows = []
        variants = []
        callsetIds = None
        for gt_variant, nextPageToken in objectGenerator(request):
            genotypemtx, variant, callsetids = gt_variant
            genotyperows.append(genotypemtx)
            variant.ClearField(b"calls")
            variants.append(variant)
            if callsetIds is None:
                callsetIds = callsetids

        for genotyperow in genotyperows:
            response.genotypes.genotypes.extend(genotyperow.genotypes)
        response.genotypes.nindividuals = len(genotyperows[0].genotypes)
        response.genotypes.nvariants = len(variants)

        response.variants.extend(variants)
        response.call_set_ids.extend(callsetIds)

        return protocol.serialize(response, return_mimetype)

    # Get requests.

    def runGetCallSet(self, id_, return_mimetype="application/json"):
        """
        Returns a callset with the given id
        """
        compoundId = datamodel.CallSetCompoundId.parse(id_)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        variantSet = dataset.getVariantSet(compoundId.variant_set_id)
        callSet = variantSet.getCallSet(id_)
        return self.runGetRequest(callSet, return_mimetype)

    def runGetInfo(self, request, return_mimetype="application/json"):
        """
        Returns information about the service including protocol version.
        """
        return protocol.serialize(protocol.GetInfoResponse(
            protocol_version=protocol.version), return_mimetype)

    def runGetVariant(self, id_, return_mimetype="application/json"):
        """
        Returns a variant with the given id
        """
        compoundId = datamodel.VariantCompoundId.parse(id_)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        variantSet = dataset.getVariantSet(compoundId.variant_set_id)
        gaVariant = variantSet.getVariant(compoundId)
        # TODO variant is a special case here, as it's returning a
        # protocol element rather than a datamodel object. We should
        # fix this for consistency.
        data = protocol.serialize(gaVariant, return_mimetype)
        return data

    def runGetBiosample(self, id_, return_mimetype="application/json"):
        """
        Runs a getBiosample request for the specified ID.
        """
        compoundId = datamodel.BiosampleCompoundId.parse(id_)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        biosample = dataset.getBiosample(id_)
        return self.runGetRequest(biosample, return_mimetype)

    def runGetIndividual(self, id_, return_mimetype="application/json"):
        """
        Runs a getIndividual request for the specified ID.
        """
        compoundId = datamodel.BiosampleCompoundId.parse(id_)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        individual = dataset.getIndividual(id_)
        return self.runGetRequest(individual, return_mimetype)

    def runGetFeature(self, id_, return_mimetype="application/json"):
        """
        Returns JSON string of the feature object corresponding to
        the feature compoundID passed in.
        """
        compoundId = datamodel.FeatureCompoundId.parse(id_)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        featureSet = dataset.getFeatureSet(compoundId.feature_set_id)
        gaFeature = featureSet.getFeature(compoundId)
        data = protocol.serialize(gaFeature, return_mimetype)
        return data

    def runGetReadGroupSet(self, id_, return_mimetype="application/json"):
        """
        Returns a readGroupSet with the given id_
        """
        compoundId = datamodel.ReadGroupSetCompoundId.parse(id_)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        readGroupSet = dataset.getReadGroupSet(id_)
        return self.runGetRequest(readGroupSet, return_mimetype)

    def runGetReadGroup(self, id_, return_mimetype="application/json"):
        """
        Returns a read group with the given id_
        """
        compoundId = datamodel.ReadGroupCompoundId.parse(id_)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        readGroupSet = dataset.getReadGroupSet(compoundId.read_group_set_id)
        readGroup = readGroupSet.getReadGroup(id_)
        return self.runGetRequest(readGroup, return_mimetype)

    def runGetReference(self, id_, return_mimetype="application/json"):
        """
        Runs a getReference request for the specified ID.
        """
        compoundId = datamodel.ReferenceCompoundId.parse(id_)
        referenceSet = self.getDataRepository().getReferenceSet(
            compoundId.reference_set_id)
        reference = referenceSet.getReference(id_)
        return self.runGetRequest(reference, return_mimetype)

    def runGetReferenceSet(self, id_, return_mimetype="application/json"):
        """
        Runs a getReferenceSet request for the specified ID.
        """
        referenceSet = self.getDataRepository().getReferenceSet(id_)
        return self.runGetRequest(referenceSet, return_mimetype)

    def runGetVariantSet(self, id_, return_mimetype="application/json"):
        """
        Runs a getVariantSet request for the specified ID.
        """
        compoundId = datamodel.VariantSetCompoundId.parse(id_)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        variantSet = dataset.getVariantSet(id_)
        return self.runGetRequest(variantSet, return_mimetype)

    def runGetFeatureSet(self, id_, return_mimetype="application/json"):
        """
        Runs a getFeatureSet request for the specified ID.
        """
        compoundId = datamodel.FeatureSetCompoundId.parse(id_)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        featureSet = dataset.getFeatureSet(id_)
        return self.runGetRequest(featureSet, return_mimetype)

    def runGetContinuousSet(self, id_, return_mimetype="application/json"):
        """
        Runs a getContinuousSet request for the specified ID.
        """
        compoundId = datamodel.ContinuousSetCompoundId.parse(id_)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        continuousSet = dataset.getContinuousSet(id_)
        return self.runGetRequest(continuousSet, return_mimetype)

    def runGetDataset(self, id_, return_mimetype="application/json"):
        """
        Runs a getDataset request for the specified ID.
        """
        dataset = self.getDataRepository().getDataset(id_)
        return self.runGetRequest(dataset, return_mimetype)

    def runGetExperiment(self, id_):
        """
        Runs a getExperiment request for the specified ID.
        """
        experiment = self.getDataRepository().getExperiment(id_)
        return self.runGetRequest(experiment)

    def runGetVariantAnnotationSet(self, id_,
                                   return_mimetype="application/json"):
        """
        Runs a getVariantSet request for the specified ID.
        """
        compoundId = datamodel.VariantAnnotationSetCompoundId.parse(id_)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        variantSet = dataset.getVariantSet(compoundId.variant_set_id)
        variantAnnotationSet = variantSet.getVariantAnnotationSet(id_)
        return self.runGetRequest(variantAnnotationSet, return_mimetype)

    def runGetRnaQuantification(self, id_, return_mimetype="application/json"):
        """
        Runs a getRnaQuantification request for the specified ID.
        """
        compoundId = datamodel.RnaQuantificationCompoundId.parse(id_)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        rnaQuantificationSet = dataset.getRnaQuantificationSet(
            compoundId.rna_quantification_set_id)
        rnaQuantification = rnaQuantificationSet.getRnaQuantification(id_)
        return self.runGetRequest(rnaQuantification, return_mimetype)

    def runGetRnaQuantificationSet(self, id_,
                                   return_mimetype="application/json"):
        """
        Runs a getRnaQuantificationSet request for the specified ID.
        """
        compoundId = datamodel.RnaQuantificationSetCompoundId.parse(id_)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        rnaQuantificationSet = dataset.getRnaQuantificationSet(id_)
        return self.runGetRequest(rnaQuantificationSet, return_mimetype)

    def runGetExpressionLevel(self, id_, return_mimetype="application/json"):
        """
        Runs a getExpressionLevel request for the specified ID.
        """
        compoundId = datamodel.ExpressionLevelCompoundId.parse(id_)
        dataset = self.getDataRepository().getDataset(compoundId.dataset_id)
        rnaQuantificationSet = dataset.getRnaQuantificationSet(
            compoundId.rna_quantification_set_id)
        rnaQuantification = rnaQuantificationSet.getRnaQuantification(
            compoundId.rna_quantification_id)
        expressionLevel = rnaQuantification.getExpressionLevel(compoundId)
        return self.runGetRequest(expressionLevel, return_mimetype)

    # Search requests.

    def runSearchReadGroupSets(self, request, return_mimetype):
        """
        Runs the specified SearchReadGroupSetsRequest.
        """
        return self.runSearchRequest(
            request, protocol.SearchReadGroupSetsRequest,
            protocol.SearchReadGroupSetsResponse,
            self.readGroupSetsGenerator,
            return_mimetype)

    def runSearchIndividuals(self, request, return_mimetype):
        """
        Runs the specified search SearchIndividualsRequest.
        """
        return self.runSearchRequest(
            request, protocol.SearchIndividualsRequest,
            protocol.SearchIndividualsResponse,
            self.individualsGenerator,
            return_mimetype)

    def runSearchBiosamples(self, request, return_mimetype):
        """
        Runs the specified SearchBiosamplesRequest.
        """
        return self.runSearchRequest(
            request, protocol.SearchBiosamplesRequest,
            protocol.SearchBiosamplesResponse,
            self.biosamplesGenerator,
            return_mimetype)

    def runSearchReads(self, request, return_mimetype):
        """
        Runs the specified SearchReadsRequest.
        """
        return self.runSearchRequest(
            request, protocol.SearchReadsRequest,
            protocol.SearchReadsResponse,
            self.readsGenerator,
            return_mimetype)

    def runSearchReferenceSets(self, request, return_mimetype):
        """
        Runs the specified SearchReferenceSetsRequest.
        """
        return self.runSearchRequest(
            request, protocol.SearchReferenceSetsRequest,
            protocol.SearchReferenceSetsResponse,
            self.referenceSetsGenerator,
            return_mimetype)

    def runSearchReferences(self, request, return_mimetype):
        """
        Runs the specified SearchReferenceRequest.
        """
        return self.runSearchRequest(
            request, protocol.SearchReferencesRequest,
            protocol.SearchReferencesResponse,
            self.referencesGenerator,
            return_mimetype)

    def runSearchVariantSets(self, request, return_mimetype):
        """
        Runs the specified SearchVariantSetsRequest.
        """
        return self.runSearchRequest(
            request, protocol.SearchVariantSetsRequest,
            protocol.SearchVariantSetsResponse,
            self.variantSetsGenerator,
            return_mimetype)

    def runSearchVariantAnnotationSets(self, request, return_mimetype):
        """
        Runs the specified SearchVariantAnnotationSetsRequest.
        """
        return self.runSearchRequest(
            request, protocol.SearchVariantAnnotationSetsRequest,
            protocol.SearchVariantAnnotationSetsResponse,
            self.variantAnnotationSetsGenerator,
            return_mimetype)

    def runSearchVariants(self, request, return_mimetype):
        """
        Runs the specified SearchVariantRequest.
        """
        return self.runSearchRequest(
            request, protocol.SearchVariantsRequest,
            protocol.SearchVariantsResponse,
            self.variantsGenerator,
            return_mimetype)

    def runSearchGenotypes(self, request, return_mimetype):
        """
        Runs the specified SearchVariantRequest.
        """
        return self.runSearchGenotypesRequest(request, return_mimetype)

    def runSearchVariantAnnotations(self, request, return_mimetype):
        """
        Runs the specified SearchVariantAnnotationsRequest.
        """
        return self.runSearchRequest(
            request, protocol.SearchVariantAnnotationsRequest,
            protocol.SearchVariantAnnotationsResponse,
            self.variantAnnotationsGenerator,
            return_mimetype)

    def runSearchCallSets(self, request, return_mimetype):
        """
        Runs the specified SearchCallSetsRequest.
        """
        return self.runSearchRequest(
            request, protocol.SearchCallSetsRequest,
            protocol.SearchCallSetsResponse,
            self.callSetsGenerator,
            return_mimetype)

    def runSearchDatasets(self, request, return_mimetype):
        """
        Runs the specified SearchDatasetsRequest.
        """
        return self.runSearchRequest(
            request, protocol.SearchDatasetsRequest,
            protocol.SearchDatasetsResponse,
            self.datasetsGenerator,
            return_mimetype)

    def runSearchExperiments(self, request, return_mimetype):
        """
        Runs the specified SearchExperimentsRequest.
        """
        return self.runSearchRequest(
            request, protocol.SearchExperimentsRequest,
            protocol.SearchExperimentsResponse,
            self.experimentsGenerator,
            return_mimetype)

    def runSearchFeatureSets(self, request, return_mimetype):
        """
        Returns a SearchFeatureSetsResponse for the specified
        SearchFeatureSetsRequest object.
        """
        return self.runSearchRequest(
            request, protocol.SearchFeatureSetsRequest,
            protocol.SearchFeatureSetsResponse,
            self.featureSetsGenerator,
            return_mimetype)

    def runSearchFeatures(self, request, return_mimetype):
        """
        Returns a SearchFeaturesResponse for the specified
        SearchFeaturesRequest object.

        :param request: JSON string representing searchFeaturesRequest
        :return: JSON string representing searchFeatureResponse
        """
        return self.runSearchRequest(
            request, protocol.SearchFeaturesRequest,
            protocol.SearchFeaturesResponse,
            self.featuresGenerator,
            return_mimetype)

    def runSearchContinuousSets(self, request, return_mimetype):
        """
        Returns a SearchContinuousSetsResponse for the specified
        SearchContinuousSetsRequest object.
        """
        return self.runSearchRequest(
            request, protocol.SearchContinuousSetsRequest,
            protocol.SearchContinuousSetsResponse,
            self.continuousSetsGenerator,
            return_mimetype)

    def runSearchContinuous(self, request, return_mimetype):
        """
        Returns a SearchContinuousResponse for the specified
        SearchContinuousRequest object.

        :param request: JSON string representing searchContinuousRequest
        :return: JSON string representing searchContinuousResponse
        """
        return self.runSearchRequest(
            request, protocol.SearchContinuousRequest,
            protocol.SearchContinuousResponse,
            self.continuousGenerator,
            return_mimetype)

    def runSearchGenotypePhenotypes(self, request, return_mimetype):
        return self.runSearchRequest(
            request, protocol.SearchGenotypePhenotypeRequest,
            protocol.SearchGenotypePhenotypeResponse,
            self.genotypesPhenotypesGenerator,
            return_mimetype)

    def runSearchPhenotypes(self, request, return_mimetype):
        return self.runSearchRequest(
            request, protocol.SearchPhenotypesRequest,
            protocol.SearchPhenotypesResponse,
            self.phenotypesGenerator,
            return_mimetype)

    def runSearchPhenotypeAssociationSets(self, request, return_mimetype):
        return self.runSearchRequest(
            request, protocol.SearchPhenotypeAssociationSetsRequest,
            protocol.SearchPhenotypeAssociationSetsResponse,
            self.phenotypeAssociationSetsGenerator,
            return_mimetype)

    def runSearchRnaQuantificationSets(self, request, return_mimetype):
        """
        Returns a SearchRnaQuantificationSetsResponse for the specified
        SearchRnaQuantificationSetsRequest object.
        """
        return self.runSearchRequest(
            request, protocol.SearchRnaQuantificationSetsRequest,
            protocol.SearchRnaQuantificationSetsResponse,
            self.rnaQuantificationSetsGenerator,
            return_mimetype)

    def runSearchRnaQuantifications(self, request, return_mimetype):
        """
        Returns a SearchRnaQuantificationResponse for the specified
        SearchRnaQuantificationRequest object.
        """
        return self.runSearchRequest(
            request, protocol.SearchRnaQuantificationsRequest,
            protocol.SearchRnaQuantificationsResponse,
            self.rnaQuantificationsGenerator,
            return_mimetype)

    def runSearchExpressionLevels(self, request, return_mimetype):
        """
        Returns a SearchExpressionLevelResponse for the specified
        SearchExpressionLevelRequest object.
        """
        return self.runSearchRequest(
            request, protocol.SearchExpressionLevelsRequest,
            protocol.SearchExpressionLevelsResponse,
            self.expressionLevelsGenerator,
            return_mimetype)
