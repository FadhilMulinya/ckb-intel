import { FastifyRequest, FastifyReply } from "fastify";
import { getEvaluationSummary, EvaluationNotFoundError } from "../services/evaluation.service.js";

/**
 * Controller = I/O. Serves the latest model evaluation metrics produced by
 * classifier-service/train_eval.py (Python) -- accuracy, precision, recall, F1,
 * confusion matrix, dataset statistics, label distribution, and when the
 * evaluation was last generated.
 */
export async function getEvaluation(
  _request: FastifyRequest,
  reply: FastifyReply
): Promise<void> {
  try {
    reply.send(getEvaluationSummary());
  } catch (err) {
    if (err instanceof EvaluationNotFoundError) {
      reply.code(503).send({ error: err.message });
      return;
    }
    throw err;
  }
}
